from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from google.cloud import bigquery

from config import Settings, build_bigquery_client, get_settings

logger = logging.getLogger(__name__)

ApprovalStatus = Literal["PENDING", "APPROVED", "REJECTED"]
ApprovalAction = Literal["UPSERT", "DELETE"]

_BOOTSTRAP_SQL = """
CREATE TABLE IF NOT EXISTS `{project}.{dataset}.{approvals_table}` (
  approval_id STRING NOT NULL,
  dataset STRING NOT NULL,
  table_name STRING NOT NULL,
  column_name STRING,
  action STRING NOT NULL,
  proposed_data STRING,
  status STRING NOT NULL,
  proposed_by STRING,
  proposed_at TIMESTAMP NOT NULL,
  reviewed_by STRING,
  reviewed_at TIMESTAMP
)
"""


@dataclass(slots=True)
class PendingApproval:
    approval_id: str
    dataset: str
    table_name: str
    column_name: str | None
    action: ApprovalAction
    proposed_data: dict[str, Any] | None
    status: ApprovalStatus
    proposed_by: str
    proposed_at: datetime
    reviewed_by: str | None
    reviewed_at: datetime | None


class ApprovalNotFoundError(Exception):
    pass


class ApprovalNotPendingError(Exception):
    pass


class CatalogApprovalQueue:
    """A lightweight approval gate for HIGH-PII column changes.

    This is a workflow *state machine*, not real access control by itself — there's no
    authentication system in this app, so "approver" is just a different self-reported name
    than the proposer, not a verified distinct identity. It exists to add a deliberate pause
    and a second look before a real, BigQuery-enforced restriction goes into effect.
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
            approvals_table=self._settings.catalog_pending_approvals_table,
        )
        self._client.query(sql).result()
        self._bootstrapped = True

    def _table_id(self) -> str:
        return f"{self._settings.gcp_project_id}.{self._settings.bigquery_dataset}.{self._settings.catalog_pending_approvals_table}"

    def propose(
        self,
        dataset: str,
        table: str,
        column: str | None,
        action: ApprovalAction,
        proposed_data: dict[str, Any] | None,
        proposed_by: str,
    ) -> str:
        self._ensure_table()
        approval_id = uuid.uuid4().hex[:16]
        sql = f"""
            INSERT INTO `{self._table_id()}`
            (approval_id, dataset, table_name, column_name, action, proposed_data, status, proposed_by, proposed_at)
            VALUES (@approval_id, @dataset, @table_name, @column_name, @action, @proposed_data, 'PENDING', @proposed_by, @proposed_at)
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("approval_id", "STRING", approval_id),
                bigquery.ScalarQueryParameter("dataset", "STRING", dataset),
                bigquery.ScalarQueryParameter("table_name", "STRING", table),
                bigquery.ScalarQueryParameter("column_name", "STRING", column),
                bigquery.ScalarQueryParameter("action", "STRING", action),
                bigquery.ScalarQueryParameter(
                    "proposed_data", "STRING", json.dumps(proposed_data) if proposed_data else None
                ),
                bigquery.ScalarQueryParameter("proposed_by", "STRING", proposed_by or "unknown"),
                bigquery.ScalarQueryParameter("proposed_at", "TIMESTAMP", datetime.now(timezone.utc)),
            ]
        )
        self._client.query(sql, job_config=job_config).result()
        return approval_id

    def get(self, approval_id: str) -> PendingApproval | None:
        self._ensure_table()
        sql = f"SELECT * FROM `{self._table_id()}` WHERE approval_id = @approval_id"
        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("approval_id", "STRING", approval_id)]
        )
        rows = list(self._client.query(sql, job_config=job_config).result())
        return self._row_to_approval(rows[0]) if rows else None

    def list_pending(self, dataset: str | None = None, table: str | None = None) -> list[PendingApproval]:
        self._ensure_table()
        conditions = ["status = 'PENDING'"]
        params = []
        if dataset:
            conditions.append("dataset = @dataset")
            params.append(bigquery.ScalarQueryParameter("dataset", "STRING", dataset))
        if table:
            conditions.append("table_name = @table_name")
            params.append(bigquery.ScalarQueryParameter("table_name", "STRING", table))
        sql = f"SELECT * FROM `{self._table_id()}` WHERE {' AND '.join(conditions)} ORDER BY proposed_at DESC"
        job_config = bigquery.QueryJobConfig(query_parameters=params)
        rows = self._client.query(sql, job_config=job_config).result()
        return [self._row_to_approval(r) for r in rows]

    def resolve(self, approval_id: str, status: Literal["APPROVED", "REJECTED"], reviewed_by: str) -> PendingApproval:
        approval = self.get(approval_id)
        if approval is None:
            raise ApprovalNotFoundError(f"No approval found with id {approval_id}")
        if approval.status != "PENDING":
            raise ApprovalNotPendingError(f"Approval {approval_id} is already {approval.status}")

        sql = f"""
            UPDATE `{self._table_id()}`
            SET status = @status, reviewed_by = @reviewed_by, reviewed_at = @reviewed_at
            WHERE approval_id = @approval_id
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("status", "STRING", status),
                bigquery.ScalarQueryParameter("reviewed_by", "STRING", reviewed_by or "unknown"),
                bigquery.ScalarQueryParameter("reviewed_at", "TIMESTAMP", datetime.now(timezone.utc)),
                bigquery.ScalarQueryParameter("approval_id", "STRING", approval_id),
            ]
        )
        self._client.query(sql, job_config=job_config).result()

        approval.status = status
        approval.reviewed_by = reviewed_by
        approval.reviewed_at = datetime.now(timezone.utc)
        return approval

    @staticmethod
    def _row_to_approval(row: Any) -> PendingApproval:
        return PendingApproval(
            approval_id=row.approval_id,
            dataset=row.dataset,
            table_name=row.table_name,
            column_name=row.column_name,
            action=row.action,
            proposed_data=json.loads(row.proposed_data) if row.proposed_data else None,
            status=row.status,
            proposed_by=row.proposed_by,
            proposed_at=row.proposed_at,
            reviewed_by=row.reviewed_by,
            reviewed_at=row.reviewed_at,
        )
