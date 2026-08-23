from __future__ import annotations

import logging
from dataclasses import dataclass

import sqlglot
from google.api_core.exceptions import BadRequest, Forbidden, GoogleAPIError
from google.cloud import bigquery
from sqlglot.errors import ParseError

from config import Settings, build_bigquery_client, get_settings

logger = logging.getLogger(__name__)

# exp.DML / exp.DDL are stable base classes that every mutating/administrative statement type
# (INSERT, UPDATE, DELETE, MERGE, CREATE, DROP, ALTER, TRUNCATE, GRANT, ...) derives from across
# sqlglot versions, so gating on them avoids hard-coding an enumeration that drifts between releases.
_DISALLOWED_EXPRESSION_TYPES = (sqlglot.exp.DML, sqlglot.exp.DDL)


class SQLGuardError(Exception):
    """Base class for all guardrail rejections. Carries the raw message so it can be fed back to the LLM."""


class NonSelectQueryError(SQLGuardError):
    pass


class SQLSyntaxError(SQLGuardError):
    pass


class ByteCapExceededError(SQLGuardError):
    def __init__(self, estimated_bytes: int, cap_bytes: int) -> None:
        self.estimated_bytes = estimated_bytes
        self.cap_bytes = cap_bytes
        super().__init__(
            f"Query would scan {estimated_bytes:,} bytes, exceeding the {cap_bytes:,} byte cap."
        )


@dataclass(frozen=True, slots=True)
class DryRunResult:
    is_valid: bool
    estimated_bytes: int
    within_byte_cap: bool


def assert_select_only(sql: str, dialect: str = "bigquery") -> None:
    """AST-level guardrail: parses the statement and rejects anything that is not a single SELECT."""
    try:
        statements = sqlglot.parse(sql, read=dialect)
    except ParseError as exc:
        raise SQLSyntaxError(f"Unable to parse SQL for guardrail check: {exc}") from exc

    if not statements or any(stmt is None for stmt in statements):
        raise NonSelectQueryError("No valid SQL statement was found in the model output.")

    if len(statements) > 1:
        raise NonSelectQueryError("Multiple statements are not permitted; only a single SELECT is allowed.")

    root = statements[0]
    if not isinstance(root, (sqlglot.exp.Select, sqlglot.exp.Union, sqlglot.exp.Subquery)):
        raise NonSelectQueryError(f"Only SELECT statements are permitted; received {type(root).__name__}.")

    for disallowed_type in _DISALLOWED_EXPRESSION_TYPES:
        if root.find(disallowed_type) is not None:
            raise NonSelectQueryError(
                f"Query contains a disallowed operation: {disallowed_type.__name__}."
            )


class BigQueryDryRunValidator:
    """Validates syntax and cost of a candidate SQL string using BigQuery's dry-run mode before execution."""

    def __init__(self, client: bigquery.Client | None = None, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = client or build_bigquery_client(self._settings)

    def validate(self, sql: str) -> DryRunResult:
        assert_select_only(sql)

        job_config = bigquery.QueryJobConfig(
            dry_run=True,
            use_query_cache=False,
            maximum_bytes_billed=self._settings.max_bytes_billed,
        )

        try:
            query_job = self._client.query(sql, job_config=job_config)
        except BadRequest as exc:
            raise SQLSyntaxError(self._extract_api_message(exc)) from exc
        except Forbidden as exc:
            raise SQLSyntaxError(self._extract_api_message(exc)) from exc
        except GoogleAPIError as exc:
            raise SQLSyntaxError(f"BigQuery rejected the query: {exc}") from exc

        estimated_bytes = query_job.total_bytes_processed or 0
        within_cap = estimated_bytes <= self._settings.max_bytes_billed

        if not within_cap:
            raise ByteCapExceededError(estimated_bytes, self._settings.max_bytes_billed)

        logger.info("Dry run OK: %s bytes estimated (cap=%s)", estimated_bytes, self._settings.max_bytes_billed)
        return DryRunResult(is_valid=True, estimated_bytes=estimated_bytes, within_byte_cap=within_cap)

    @staticmethod
    def _extract_api_message(exc: GoogleAPIError) -> str:
        return getattr(exc, "message", None) or str(exc)
