from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from google.api_core.exceptions import NotFound
from google.cloud import bigquery
from pydantic import BaseModel, Field
from sqlalchemy import create_engine

from batch_pipeline import (
    ANOMALY_RESULTS_TABLE,
    PIPELINE_RUN_LOG_TABLE,
    VALID_REVIEW_STATUSES,
    BatchPipeline,
    PipelineError,
)
from cache import CachedQueryResult, SemanticCacheService
from catalog_api import router as catalog_router
from config import Settings, build_bigquery_client, get_settings
from feature_store import FEATURE_TABLE_NAME
from metadata_indexer import MetadataIndexBuilder, SchemaExtractor
from query_engine import (
    GuardedSQLDatabase,
    NL2SQLEngine,
    QueryGenerationFailedError,
    configure_global_llama_settings,
)
from sql_guard import SQLGuardError

logging.basicConfig(level=get_settings().log_level)
logger = logging.getLogger(__name__)


class AppState:
    settings: Settings | None = None
    engine: NL2SQLEngine | None = None
    cache_service: SemanticCacheService | None = None
    bq_client: bigquery.Client | None = None
    pipeline_running: bool = False
    ready: bool = False
    startup_error: str | None = None


state = AppState()


def _initialize_application(settings: Settings) -> None:
    configure_global_llama_settings(settings)

    bq_client = build_bigquery_client(settings)
    # Passing the already-authenticated client avoids sqlalchemy-bigquery resolving its own
    # credentials implicitly (via ambient GOOGLE_APPLICATION_CREDENTIALS / ADC), which can
    # silently authenticate table reflection as a different, unintended principal.
    engine = create_engine(settings.bigquery_connection_string, connect_args={"client": bq_client})
    sql_database = GuardedSQLDatabase(
        engine,
        schema=settings.bigquery_dataset,
        bq_client=bq_client,
        settings=settings,
    )

    index_builder = MetadataIndexBuilder(
        sql_database=sql_database,
        schema_extractor=SchemaExtractor(client=bq_client, settings=settings),
        settings=settings,
    )
    object_index = index_builder.build()

    state.engine = NL2SQLEngine(object_index=object_index, sql_database=sql_database, settings=settings)
    state.cache_service = SemanticCacheService(settings=settings)
    state.bq_client = bq_client
    state.ready = True
    logger.info("NL2SQL engine initialized for dataset %s.%s", settings.gcp_project_id, settings.bigquery_dataset)


def _require_ready() -> None:
    if state.ready:
        return
    if state.startup_error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Service startup failed: {state.startup_error}",
        )
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Service is starting (loading schema index); retry in a minute.",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    state.settings = settings
    state.pipeline_running = False
    state.ready = False
    state.startup_error = None

    async def _background_startup() -> None:
        try:
            await run_in_threadpool(_initialize_application, settings)
        except Exception as exc:
            logger.exception("Application startup failed.")
            state.startup_error = str(exc)

    asyncio.create_task(_background_startup())
    yield
    logger.info("Shutting down NL2SQL service.")


app = FastAPI(
    title="NL2SQL BigQuery Engine",
    description="Natural language to GoogleSQL query engine with RAG schema retrieval, semantic caching, and self-healing validation.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().api_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(catalog_router)


class QueryRequest(BaseModel):
    user_prompt: str = Field(..., min_length=1, max_length=2000, description="Natural language question about the dataset.")


class QueryResponseData(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]


class QueryResponse(BaseModel):
    sql: str
    execution_time_ms: float
    estimated_bytes: int
    data: QueryResponseData
    cache_hit: bool
    used_fallback_model: bool = False
    attempts: int = 1


@app.get("/api/v1/health")
async def health() -> dict[str, str]:
    if state.startup_error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "failed", "error": state.startup_error},
        )
    if not state.ready:
        return {"status": "starting"}
    return {"status": "ok"}


@app.post("/api/v1/query", response_model=QueryResponse)
async def run_query(request: QueryRequest) -> QueryResponse:
    _require_ready()
    request_start = time.perf_counter()

    cached = await run_in_threadpool(state.cache_service.lookup, request.user_prompt)
    if cached is not None:
        logger.info("Semantic cache hit for prompt: %.80s", request.user_prompt)
        return QueryResponse(
            sql=cached.sql,
            execution_time_ms=(time.perf_counter() - request_start) * 1000,
            estimated_bytes=cached.estimated_bytes,
            data=QueryResponseData(columns=cached.columns, rows=cached.rows),
            cache_hit=True,
        )

    try:
        result = await run_in_threadpool(state.engine.run, request.user_prompt)
    except QueryGenerationFailedError as exc:
        logger.warning("Query generation failed after %d attempts: %s", exc.attempts, exc.last_error)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unable to generate a valid SQL query after {exc.attempts} attempts. Last error: {exc.last_error}",
        ) from exc
    except SQLGuardError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - surface as a clean 500 rather than an unhandled traceback
        logger.exception("Unexpected failure while processing query.")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error.") from exc

    payload = result.payload
    await run_in_threadpool(
        state.cache_service.store,
        request.user_prompt,
        CachedQueryResult(
            sql=payload.sql,
            columns=payload.columns,
            rows=payload.rows,
            estimated_bytes=payload.estimated_bytes,
        ),
    )

    return QueryResponse(
        sql=payload.sql,
        execution_time_ms=payload.execution_time_ms,
        estimated_bytes=payload.estimated_bytes,
        data=QueryResponseData(columns=payload.columns, rows=payload.rows),
        cache_hit=False,
        used_fallback_model=result.used_fallback_model,
        attempts=result.attempts,
    )


# ============================================================================
# FWA Feature Store & Anomaly Engine
# ============================================================================


class PipelineRunResponse(BaseModel):
    run_id: str
    status: str
    message: str


class PipelineRunLogEntry(BaseModel):
    run_id: str
    started_at: datetime
    completed_at: datetime | None
    status: str
    total_claims_scored: int | None
    anomalies_flagged: int | None
    error_message: str | None
    model_artifact_uri: str | None


class RiskScoreBucket(BaseModel):
    bucket_start: float
    bucket_end: float
    count: int


class MetricsResponse(BaseModel):
    total_claims: int
    total_anomalies: int
    anomaly_rate: float
    review_status_counts: dict[str, int]
    risk_score_distribution: list[RiskScoreBucket]
    latest_run: PipelineRunLogEntry | None
    recent_runs: list[PipelineRunLogEntry]


class RiskDriver(BaseModel):
    feature: str
    value: float
    shap_value: float
    description: str


class ClaimReviewItem(BaseModel):
    claim_id: str
    member_id: str
    plan_id: str
    claim_type: str
    claim_status: str
    service_start_date: str
    total_billed_amount: float
    total_allowed_amount: float
    total_paid_amount: float
    anomaly_risk_score: float
    is_anomaly: int
    top_risk_drivers: list[RiskDriver]
    review_status: str
    scored_at: datetime


class ClaimReviewResponse(BaseModel):
    items: list[ClaimReviewItem]
    total_count: int


class ClaimStatusUpdateRequest(BaseModel):
    review_status: Literal["PENDING_REVIEW", "CONFIRMED_FRAUD", "FALSE_POSITIVE", "CLEARED"]


class ClaimStatusUpdateResponse(BaseModel):
    claim_id: str
    review_status: str
    reviewed_at: datetime | None


def _dataset_ref() -> str:
    settings = state.settings
    return f"{settings.gcp_project_id}.{settings.bigquery_dataset}"


def _run_pipeline_background(run_id: str) -> None:
    try:
        BatchPipeline(client=state.bq_client, settings=state.settings).run(run_id=run_id)
    except PipelineError:
        logger.exception("Background pipeline run %s failed.", run_id)
    finally:
        state.pipeline_running = False


@app.post("/api/v1/pipeline/run", response_model=PipelineRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_pipeline_run(background_tasks: BackgroundTasks) -> PipelineRunResponse:
    _require_ready()
    if state.pipeline_running:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A pipeline run is already in progress."
        )

    run_id = uuid.uuid4().hex[:12]
    state.pipeline_running = True
    background_tasks.add_task(_run_pipeline_background, run_id)

    return PipelineRunResponse(
        run_id=run_id, status="RUNNING", message="Feature refresh + anomaly scoring run started."
    )


def _fetch_metrics() -> MetricsResponse:
    dataset_ref = _dataset_ref()
    client = state.bq_client

    total_claims = 0
    total_anomalies = 0
    review_status_counts: dict[str, int] = {}
    risk_score_distribution: list[RiskScoreBucket] = []

    try:
        totals_row = next(
            iter(
                client.query(
                    f"""
                    SELECT COUNT(*) AS total_claims, COUNTIF(is_anomaly = -1) AS total_anomalies
                    FROM `{dataset_ref}.{ANOMALY_RESULTS_TABLE}`
                    """
                ).result()
            ),
            None,
        )
        if totals_row is not None:
            total_claims = int(totals_row.total_claims)
            total_anomalies = int(totals_row.total_anomalies)

        for row in client.query(
            f"""
            SELECT review_status, COUNT(*) AS status_count
            FROM `{dataset_ref}.{ANOMALY_RESULTS_TABLE}`
            GROUP BY review_status
            """
        ).result():
            review_status_counts[row.review_status] = int(row.status_count)

        for row in client.query(
            f"""
            SELECT
              CAST(FLOOR(LEAST(anomaly_risk_score, 99.999) / 10) * 10 AS FLOAT64) AS bucket_start,
              COUNT(*) AS bucket_count
            FROM `{dataset_ref}.{ANOMALY_RESULTS_TABLE}`
            GROUP BY bucket_start
            ORDER BY bucket_start
            """
        ).result():
            risk_score_distribution.append(
                RiskScoreBucket(
                    bucket_start=float(row.bucket_start),
                    bucket_end=float(row.bucket_start) + 10.0,
                    count=int(row.bucket_count),
                )
            )
    except NotFound:
        logger.info("claim_anomaly_results does not exist yet; no pipeline run has completed.")

    recent_runs: list[PipelineRunLogEntry] = []
    try:
        for row in client.query(
            f"""
            SELECT run_id, started_at, completed_at, status, total_claims_scored,
                   anomalies_flagged, error_message, model_artifact_uri
            FROM `{dataset_ref}.{PIPELINE_RUN_LOG_TABLE}`
            ORDER BY started_at DESC
            LIMIT 10
            """
        ).result():
            recent_runs.append(
                PipelineRunLogEntry(
                    run_id=row.run_id,
                    started_at=row.started_at,
                    completed_at=row.completed_at,
                    status=row.status,
                    total_claims_scored=row.total_claims_scored,
                    anomalies_flagged=row.anomalies_flagged,
                    error_message=row.error_message,
                    model_artifact_uri=row.model_artifact_uri,
                )
            )
    except NotFound:
        logger.info("pipeline_run_log does not exist yet; no pipeline run has been triggered.")

    return MetricsResponse(
        total_claims=total_claims,
        total_anomalies=total_anomalies,
        anomaly_rate=round(total_anomalies / total_claims, 4) if total_claims else 0.0,
        review_status_counts=review_status_counts,
        risk_score_distribution=risk_score_distribution,
        latest_run=recent_runs[0] if recent_runs else None,
        recent_runs=recent_runs,
    )


@app.get("/api/v1/metrics", response_model=MetricsResponse)
async def get_metrics() -> MetricsResponse:
    _require_ready()
    return await run_in_threadpool(_fetch_metrics)


def _fetch_claims_for_review(
    review_status: str, min_score: float, limit: int, offset: int
) -> ClaimReviewResponse:
    dataset_ref = _dataset_ref()
    client = state.bq_client

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("review_status", "STRING", review_status),
            bigquery.ScalarQueryParameter("min_score", "FLOAT64", min_score),
            bigquery.ScalarQueryParameter("limit", "INT64", limit),
            bigquery.ScalarQueryParameter("offset", "INT64", offset),
        ]
    )

    try:
        count_row = next(
            iter(
                client.query(
                    f"""
                    SELECT COUNT(*) AS total_count
                    FROM `{dataset_ref}.{ANOMALY_RESULTS_TABLE}`
                    WHERE review_status = @review_status AND anomaly_risk_score >= @min_score
                    """,
                    job_config=job_config,
                ).result()
            ),
            None,
        )
        total_count = int(count_row.total_count) if count_row is not None else 0

        rows = client.query(
            f"""
            SELECT
              r.claim_id, f.member_id, f.plan_id, f.claim_type, f.claim_status,
              CAST(f.service_start_date AS STRING) AS service_start_date,
              f.total_billed_amount, f.total_allowed_amount, f.total_paid_amount,
              r.anomaly_risk_score, r.is_anomaly, r.top_risk_drivers, r.review_status, r.scored_at
            FROM `{dataset_ref}.{ANOMALY_RESULTS_TABLE}` r
            JOIN `{dataset_ref}.{FEATURE_TABLE_NAME}` f ON r.claim_id = f.claim_id
            WHERE r.review_status = @review_status AND r.anomaly_risk_score >= @min_score
            ORDER BY r.anomaly_risk_score DESC
            LIMIT @limit OFFSET @offset
            """,
            job_config=job_config,
        ).result()
    except NotFound:
        return ClaimReviewResponse(items=[], total_count=0)

    items = [
        ClaimReviewItem(
            claim_id=row.claim_id,
            member_id=row.member_id,
            plan_id=row.plan_id,
            claim_type=row.claim_type,
            claim_status=row.claim_status,
            service_start_date=row.service_start_date,
            total_billed_amount=float(row.total_billed_amount),
            total_allowed_amount=float(row.total_allowed_amount),
            total_paid_amount=float(row.total_paid_amount),
            anomaly_risk_score=float(row.anomaly_risk_score),
            is_anomaly=int(row.is_anomaly),
            top_risk_drivers=[RiskDriver(**d) for d in json.loads(row.top_risk_drivers)],
            review_status=row.review_status,
            scored_at=row.scored_at,
        )
        for row in rows
    ]
    return ClaimReviewResponse(items=items, total_count=total_count)


@app.get("/api/v1/claims/review", response_model=ClaimReviewResponse)
async def get_claims_for_review(
    review_status: str = "PENDING_REVIEW",
    min_score: float | None = None,
    limit: int = 50,
    offset: int = 0,
) -> ClaimReviewResponse:
    _require_ready()
    if review_status not in VALID_REVIEW_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"review_status must be one of {VALID_REVIEW_STATUSES}",
        )
    threshold = min_score if min_score is not None else state.settings.anomaly_review_score_threshold
    return await run_in_threadpool(_fetch_claims_for_review, review_status, threshold, limit, offset)


def _update_claim_status(claim_id: str, review_status: str) -> ClaimStatusUpdateResponse:
    dataset_ref = _dataset_ref()
    client = state.bq_client

    update_job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("review_status", "STRING", review_status),
            bigquery.ScalarQueryParameter("claim_id", "STRING", claim_id),
        ]
    )
    update_job = client.query(
        f"""
        UPDATE `{dataset_ref}.{ANOMALY_RESULTS_TABLE}`
        SET review_status = @review_status, reviewed_at = CURRENT_TIMESTAMP()
        WHERE claim_id = @claim_id
        """,
        job_config=update_job_config,
    )
    update_job.result()

    if not update_job.num_dml_affected_rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Claim '{claim_id}' was not found in {ANOMALY_RESULTS_TABLE}.",
        )

    select_job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("claim_id", "STRING", claim_id)]
    )
    result_row = next(
        iter(
            client.query(
                f"""
                SELECT review_status, reviewed_at
                FROM `{dataset_ref}.{ANOMALY_RESULTS_TABLE}`
                WHERE claim_id = @claim_id
                """,
                job_config=select_job_config,
            ).result()
        )
    )
    return ClaimStatusUpdateResponse(
        claim_id=claim_id, review_status=result_row.review_status, reviewed_at=result_row.reviewed_at
    )


@app.patch("/api/v1/claims/{claim_id}/status", response_model=ClaimStatusUpdateResponse)
async def update_claim_status(claim_id: str, request: ClaimStatusUpdateRequest) -> ClaimStatusUpdateResponse:
    _require_ready()
    return await run_in_threadpool(_update_claim_status, claim_id, request.review_status)
