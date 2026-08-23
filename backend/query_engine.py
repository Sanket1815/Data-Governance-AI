from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from google.cloud import bigquery
from llama_index.core import Settings as LlamaIndexSettings
from llama_index.core import SQLDatabase
from llama_index.core.llms import LLM
from llama_index.core.indices.struct_store.sql_retriever import NLSQLRetriever
from llama_index.core.objects import ObjectIndex

from config import Settings, build_bigquery_client, get_settings
from sql_guard import BigQueryDryRunValidator, SQLGuardError, assert_select_only

logger = logging.getLogger(__name__)


class QueryGenerationFailedError(Exception):
    def __init__(self, attempts: int, last_error: str) -> None:
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(
            f"Failed to produce a valid SQL query after {attempts} attempts. Last error: {last_error}"
        )


@dataclass(slots=True)
class QueryExecutionPayload:
    sql: str
    columns: list[str]
    rows: list[dict]
    estimated_bytes: int
    execution_time_ms: float


@dataclass(slots=True)
class QueryEngineResult:
    payload: QueryExecutionPayload
    used_fallback_model: bool
    attempts: int


def configure_global_llama_settings(settings: Settings | None = None) -> None:
    """Sets the process-wide LlamaIndex embedding model so metadata_indexer and query_engine stay consistent."""
    settings = settings or get_settings()
    if settings.llm_provider == "gemini":
        from llama_index.embeddings.google_genai import GoogleGenAIEmbedding

        LlamaIndexSettings.embed_model = GoogleGenAIEmbedding(
            model_name=settings.embedding_model,
            api_key=settings.google_api_key,
        )
    else:
        from llama_index.embeddings.openai import OpenAIEmbedding

        LlamaIndexSettings.embed_model = OpenAIEmbedding(
            model="text-embedding-3-small",
            api_key=settings.openai_api_key,
        )


def build_llm(model_name: str, settings: Settings | None = None) -> LLM:
    settings = settings or get_settings()
    if settings.llm_provider == "gemini":
        from llama_index.llms.google_genai import GoogleGenAI

        # Gemini's "thinking" models (flash/pro alike) spend part of the output token budget on
        # internal reasoning before emitting the actual SQL text; the pro tier can't even disable
        # thinking (thinking_budget=0 is rejected outright). Leaving max_tokens at its small default
        # lets that reasoning alone exhaust the budget and truncate the response before any SQL comes
        # out, so it's set generously here rather than tuned per model tier.
        return GoogleGenAI(
            model=model_name,
            api_key=settings.google_api_key,
            temperature=0.0,
            max_tokens=8192,
        )

    from llama_index.llms.openai import OpenAI

    return OpenAI(model=model_name, api_key=settings.openai_api_key, temperature=0.0)


class GuardedSQLDatabase(SQLDatabase):
    """SQLDatabase subclass that enforces AST + dry-run guardrails on every generated query before execution.

    The last successful execution is stashed on `self.last_execution` rather than relying solely on
    LlamaIndex's response.metadata propagation, since that plumbing has shifted across library versions
    and we need a stable contract for the FastAPI layer to consume.
    """

    def __init__(
        self,
        *args,
        bq_client: bigquery.Client | None = None,
        settings: Settings | None = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._settings = settings or get_settings()
        self._bq_client = bq_client or build_bigquery_client(self._settings)
        self._validator = BigQueryDryRunValidator(client=self._bq_client, settings=self._settings)
        self.last_execution: QueryExecutionPayload | None = None

    def run_sql(self, command: str) -> tuple[str, dict]:
        assert_select_only(command)
        self._validator.validate(command)

        start = time.perf_counter()
        job_config = bigquery.QueryJobConfig(
            maximum_bytes_billed=self._settings.max_bytes_billed,
            use_query_cache=True,
        )
        query_job = self._bq_client.query(command, job_config=job_config)
        result_iterator = query_job.result(max_results=self._settings.query_result_row_limit)
        rows = [dict(row.items()) for row in result_iterator]
        columns = [column_field.name for column_field in result_iterator.schema]
        elapsed_ms = (time.perf_counter() - start) * 1000

        payload = QueryExecutionPayload(
            sql=command,
            columns=columns,
            rows=rows,
            estimated_bytes=query_job.total_bytes_processed or 0,
            execution_time_ms=elapsed_ms,
        )
        self.last_execution = payload

        result_str = f"[{len(rows)} rows returned]"
        metadata = {"result": rows, "col_keys": columns}
        return result_str, metadata


class NL2SQLEngine:
    """Orchestrates retrieval-augmented SQL generation with model tiering and an automated self-healing loop."""

    def __init__(
        self,
        object_index: ObjectIndex,
        sql_database: GuardedSQLDatabase,
        settings: Settings | None = None,
    ) -> None:
        self._object_index = object_index
        self._sql_database = sql_database
        self._settings = settings or get_settings()
        self._primary_model, self._fallback_model = self._resolve_model_names()

    def _resolve_model_names(self) -> tuple[str, str]:
        if self._settings.llm_provider == "gemini":
            return self._settings.gemini_primary_model, self._settings.gemini_fallback_model
        return self._settings.openai_primary_model, self._settings.openai_fallback_model

    def _build_sql_retriever(self, llm: LLM) -> NLSQLRetriever:
        # NLSQLRetriever is what SQLTableRetrieverQueryEngine wraps internally for RAG-based table
        # retrieval + SQL generation/execution. We build it directly (with handle_sql_errors=False)
        # because the query engine's public constructor has no way to disable NLSQLRetriever's default
        # behavior of catching run_sql() exceptions and returning them as inert "Error: ..." text nodes
        # instead of raising — which would silently swallow every guardrail failure and break self-healing.
        table_retriever = self._object_index.as_retriever(similarity_top_k=self._settings.table_retriever_top_k)
        return NLSQLRetriever(
            self._sql_database,
            llm=llm,
            table_retriever=table_retriever,
            handle_sql_errors=False,
        )

    def run(self, user_prompt: str) -> QueryEngineResult:
        current_prompt = user_prompt
        last_error: str | None = None
        used_fallback = False
        max_attempts = self._settings.self_healing_max_retries + 1
        fallback_after_attempt = max(1, max_attempts // 2)

        for attempt in range(1, max_attempts + 1):
            model_name = self._fallback_model if used_fallback else self._primary_model
            llm = build_llm(model_name, self._settings)
            sql_retriever = self._build_sql_retriever(llm)

            try:
                sql_retriever.retrieve_with_metadata(current_prompt)
            except SQLGuardError as exc:
                last_error = str(exc)
                logger.warning("Attempt %d/%d failed guardrail check: %s", attempt, max_attempts, last_error)
                current_prompt = self._build_repair_prompt(user_prompt, last_error)
                if attempt >= fallback_after_attempt:
                    used_fallback = True
                continue
            except Exception as exc:  # noqa: BLE001 - any provider/network failure should trigger self-healing, not crash
                last_error = str(exc)
                logger.exception("Unexpected error on attempt %d/%d", attempt, max_attempts)
                if attempt >= fallback_after_attempt:
                    used_fallback = True
                continue

            if self._sql_database.last_execution is not None:
                result = QueryEngineResult(
                    payload=self._sql_database.last_execution,
                    used_fallback_model=used_fallback,
                    attempts=attempt,
                )
                self._sql_database.last_execution = None
                return result

        raise QueryGenerationFailedError(attempts=max_attempts, last_error=last_error or "Unknown error")

    @staticmethod
    def _build_repair_prompt(original_prompt: str, error_message: str) -> str:
        return (
            f"{original_prompt}\n\n"
            f"IMPORTANT: A previous attempt produced invalid SQL. BigQuery returned this exact error: "
            f'"{error_message}". Generate a corrected GoogleSQL (BigQuery Standard SQL) query that resolves it.'
        )
