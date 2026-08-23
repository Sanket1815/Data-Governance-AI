from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from google.cloud import bigquery

from config import Settings, build_bigquery_client, get_settings

logger = logging.getLogger(__name__)

_BOOTSTRAP_SQL = """
CREATE TABLE IF NOT EXISTS `{project}.{dataset}.{audit_table}` (
  audit_id STRING NOT NULL,
  dataset STRING NOT NULL,
  table_name STRING NOT NULL,
  column_name STRING,
  action STRING NOT NULL,
  old_value STRING,
  new_value STRING,
  changed_by STRING,
  changed_at TIMESTAMP NOT NULL
)
"""


@dataclass(slots=True)
class AuditEntry:
    audit_id: str
    dataset: str
    table_name: str
    column_name: str | None
    action: str
    old_value: dict[str, Any] | None
    new_value: dict[str, Any] | None
    changed_by: str
    changed_at: datetime


class CatalogAuditLog:
    """Records who changed a governance tag, what it was before/after, and when.

    There's no authentication system anywhere in this app, so `changed_by` is self-reported
    free text from the request rather than a verified identity — it's an audit trail of
    what changed and when, with an honest, unverified label for who claimed to change it.
    """

    def __init__(self, client: bigquery.Client | None = None, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = client or build_bigquery_client(self._settings)
        self._bootstrapped = False

    def _ensure_table(self) -> None:
        if self._bootstrapped:
            return
        sql = _BOOTSTRAP_SQL.format(
            project=self._settings.gcp_project_id,
            dataset=self._settings.bigquery_dataset,
            audit_table=self._settings.catalog_audit_log_table,
        )
        self._client.query(sql).result()
        self._bootstrapped = True

    def record(
        self,
        dataset: str,
        table: str,
        column: str | None,
        action: str,
        old_value: dict[str, Any] | None,
        new_value: dict[str, Any] | None,
        changed_by: str,
    ) -> None:
        self._ensure_table()
        table_id = f"{self._settings.gcp_project_id}.{self._settings.bigquery_dataset}.{self._settings.catalog_audit_log_table}"
        sql = f"""
            INSERT INTO `{table_id}`
            (audit_id, dataset, table_name, column_name, action, old_value, new_value, changed_by, changed_at)
            VALUES (@audit_id, @dataset, @table_name, @column_name, @action, @old_value, @new_value, @changed_by, @changed_at)
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("audit_id", "STRING", uuid.uuid4().hex[:16]),
                bigquery.ScalarQueryParameter("dataset", "STRING", dataset),
                bigquery.ScalarQueryParameter("table_name", "STRING", table),
                bigquery.ScalarQueryParameter("column_name", "STRING", column),
                bigquery.ScalarQueryParameter("action", "STRING", action),
                bigquery.ScalarQueryParameter("old_value", "STRING", json.dumps(old_value) if old_value else None),
                bigquery.ScalarQueryParameter("new_value", "STRING", json.dumps(new_value) if new_value else None),
                bigquery.ScalarQueryParameter("changed_by", "STRING", changed_by or "unknown"),
                bigquery.ScalarQueryParameter("changed_at", "TIMESTAMP", datetime.now(timezone.utc)),
            ]
        )
        self._client.query(sql, job_config=job_config).result()

    def list_for_table(self, dataset: str, table: str, limit: int = 50) -> list[AuditEntry]:
        self._ensure_table()
        table_id = f"{self._settings.gcp_project_id}.{self._settings.bigquery_dataset}.{self._settings.catalog_audit_log_table}"
        sql = f"""
            SELECT audit_id, dataset, table_name, column_name, action, old_value, new_value, changed_by, changed_at
            FROM `{table_id}`
            WHERE dataset = @dataset AND table_name = @table_name
            ORDER BY changed_at DESC
            LIMIT @limit
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("dataset", "STRING", dataset),
                bigquery.ScalarQueryParameter("table_name", "STRING", table),
                bigquery.ScalarQueryParameter("limit", "INT64", limit),
            ]
        )
        rows = self._client.query(sql, job_config=job_config).result()
        return [
            AuditEntry(
                audit_id=r.audit_id,
                dataset=r.dataset,
                table_name=r.table_name,
                column_name=r.column_name,
                action=r.action,
                old_value=json.loads(r.old_value) if r.old_value else None,
                new_value=json.loads(r.new_value) if r.new_value else None,
                changed_by=r.changed_by,
                changed_at=r.changed_at,
            )
            for r in rows
        ]
