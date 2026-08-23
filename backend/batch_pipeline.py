from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from google.cloud import bigquery

from config import Settings, build_bigquery_client, get_settings
from feature_store import FeatureStoreBuilder
from train_isolation_forest import IsolationForestTrainer

logger = logging.getLogger(__name__)

ANOMALY_RESULTS_TABLE = "claim_anomaly_results"
ANOMALY_RESULTS_STAGING_TABLE = "claim_anomaly_results_staging"
PIPELINE_RUN_LOG_TABLE = "pipeline_run_log"

DEFAULT_REVIEW_STATUS = "PENDING_REVIEW"
VALID_REVIEW_STATUSES = (DEFAULT_REVIEW_STATUS, "CONFIRMED_FRAUD", "FALSE_POSITIVE", "CLEARED")

_BOOTSTRAP_SQL = """
CREATE TABLE IF NOT EXISTS `{project}.{dataset}.{results_table}` (
  claim_id STRING NOT NULL,
  anomaly_risk_score FLOAT64,
  is_anomaly INT64,
  top_risk_drivers STRING,
  review_status STRING,
  model_version STRING,
  scored_at TIMESTAMP,
  reviewed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS `{project}.{dataset}.{run_log_table}` (
  run_id STRING NOT NULL,
  started_at TIMESTAMP,
  completed_at TIMESTAMP,
  status STRING,
  total_claims_scored INT64,
  anomalies_flagged INT64,
  error_message STRING,
  model_artifact_uri STRING
);
"""

_MERGE_SQL = """
MERGE `{project}.{dataset}.{results_table}` T
USING `{project}.{dataset}.{staging_table}` S
ON T.claim_id = S.claim_id
WHEN MATCHED THEN UPDATE SET
  anomaly_risk_score = S.anomaly_risk_score,
  is_anomaly = S.is_anomaly,
  top_risk_drivers = S.top_risk_drivers,
  model_version = S.model_version,
  scored_at = S.scored_at
WHEN NOT MATCHED THEN INSERT (
  claim_id, anomaly_risk_score, is_anomaly, top_risk_drivers, review_status, model_version, scored_at
) VALUES (
  S.claim_id, S.anomaly_risk_score, S.is_anomaly, S.top_risk_drivers, '{default_status}', S.model_version, S.scored_at
)
"""


class PipelineError(Exception):
    pass


@dataclass(slots=True)
class PipelineRunResult:
    run_id: str
    total_claims_scored: int
    anomalies_flagged: int
    model_artifact_uri: str
    started_at: datetime
    completed_at: datetime


class BatchPipeline:
    """Orchestrates a full feature refresh -> train -> score -> publish cycle for the FWA anomaly engine."""

    def __init__(self, client: bigquery.Client | None = None, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = client or build_bigquery_client(self._settings)
        self._feature_store = FeatureStoreBuilder(client=self._client, settings=self._settings)
        self._trainer = IsolationForestTrainer(client=self._client, settings=self._settings)

    def run(self, run_id: str | None = None) -> PipelineRunResult:
        run_id = run_id or uuid.uuid4().hex[:12]
        started_at = datetime.now(timezone.utc)
        self._bootstrap_tables()
        self._log_run_start(run_id, started_at)

        try:
            logger.info("[%s] Refreshing feature store...", run_id)
            self._feature_store.refresh()

            logger.info("[%s] Loading features and training model...", run_id)
            features_df = self._trainer.load_features()
            if features_df.empty:
                raise PipelineError("claim_feature_store returned zero rows; aborting run.")

            training = self._trainer.train(features_df)

            logger.info("[%s] Scoring %d claims...", run_id, len(features_df))
            scoring = self._trainer.score(features_df, training)

            model_artifact_uri = self._trainer.save_artifact(training, run_id)

            self._publish_results(scoring.scored_df, run_id)

            completed_at = datetime.now(timezone.utc)
            result = PipelineRunResult(
                run_id=run_id,
                total_claims_scored=len(scoring.scored_df),
                anomalies_flagged=scoring.anomaly_count,
                model_artifact_uri=model_artifact_uri,
                started_at=started_at,
                completed_at=completed_at,
            )
            self._log_run_success(result)
            logger.info(
                "[%s] Pipeline complete: %d claims scored, %d anomalies flagged.",
                run_id,
                result.total_claims_scored,
                result.anomalies_flagged,
            )
            return result
        except Exception as exc:
            logger.exception("[%s] Pipeline run failed.", run_id)
            self._log_run_failure(run_id, str(exc))
            raise PipelineError(f"Pipeline run {run_id} failed: {exc}") from exc

    def _bootstrap_tables(self) -> None:
        sql = _BOOTSTRAP_SQL.format(
            project=self._settings.gcp_project_id,
            dataset=self._settings.bigquery_dataset,
            results_table=ANOMALY_RESULTS_TABLE,
            run_log_table=PIPELINE_RUN_LOG_TABLE,
        )
        for statement in sql.split(";"):
            if statement.strip():
                self._client.query(statement).result()

    def _publish_results(self, scored_df, run_id: str) -> None:
        scored_df = scored_df.copy()
        scored_df["model_version"] = run_id
        scored_df["scored_at"] = datetime.now(timezone.utc)

        staging_table_id = (
            f"{self._settings.gcp_project_id}.{self._settings.bigquery_dataset}.{ANOMALY_RESULTS_STAGING_TABLE}"
        )
        job_config = bigquery.LoadJobConfig(write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE)
        load_job = self._client.load_table_from_dataframe(scored_df, staging_table_id, job_config=job_config)
        load_job.result()

        merge_sql = _MERGE_SQL.format(
            project=self._settings.gcp_project_id,
            dataset=self._settings.bigquery_dataset,
            results_table=ANOMALY_RESULTS_TABLE,
            staging_table=ANOMALY_RESULTS_STAGING_TABLE,
            default_status=DEFAULT_REVIEW_STATUS,
        )
        self._client.query(merge_sql).result()

    def _log_run_start(self, run_id: str, started_at: datetime) -> None:
        sql = f"""
            INSERT INTO `{self._settings.gcp_project_id}.{self._settings.bigquery_dataset}.{PIPELINE_RUN_LOG_TABLE}`
            (run_id, started_at, status)
            VALUES (@run_id, @started_at, 'RUNNING')
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("run_id", "STRING", run_id),
                bigquery.ScalarQueryParameter("started_at", "TIMESTAMP", started_at),
            ]
        )
        self._client.query(sql, job_config=job_config).result()

    def _log_run_success(self, result: PipelineRunResult) -> None:
        sql = f"""
            UPDATE `{self._settings.gcp_project_id}.{self._settings.bigquery_dataset}.{PIPELINE_RUN_LOG_TABLE}`
            SET completed_at = @completed_at,
                status = 'SUCCESS',
                total_claims_scored = @total_claims_scored,
                anomalies_flagged = @anomalies_flagged,
                model_artifact_uri = @model_artifact_uri
            WHERE run_id = @run_id
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("completed_at", "TIMESTAMP", result.completed_at),
                bigquery.ScalarQueryParameter("total_claims_scored", "INT64", result.total_claims_scored),
                bigquery.ScalarQueryParameter("anomalies_flagged", "INT64", result.anomalies_flagged),
                bigquery.ScalarQueryParameter("model_artifact_uri", "STRING", result.model_artifact_uri),
                bigquery.ScalarQueryParameter("run_id", "STRING", result.run_id),
            ]
        )
        self._client.query(sql, job_config=job_config).result()

    def _log_run_failure(self, run_id: str, error_message: str) -> None:
        sql = f"""
            UPDATE `{self._settings.gcp_project_id}.{self._settings.bigquery_dataset}.{PIPELINE_RUN_LOG_TABLE}`
            SET completed_at = @completed_at,
                status = 'FAILED',
                error_message = @error_message
            WHERE run_id = @run_id
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("completed_at", "TIMESTAMP", datetime.now(timezone.utc)),
                bigquery.ScalarQueryParameter("error_message", "STRING", error_message[:2000]),
                bigquery.ScalarQueryParameter("run_id", "STRING", run_id),
            ]
        )
        self._client.query(sql, job_config=job_config).result()
