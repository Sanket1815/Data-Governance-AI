from __future__ import annotations

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from google.cloud import dlp_v2

from config import Settings, build_bigquery_client, build_credentials, get_settings

logger = logging.getLogger(__name__)

# A bounded, healthcare/insurance-relevant subset of DLP's built-in infoTypes — not the full
# catalog (which is hundreds of types and would make a synchronous scan slow for no benefit
# on this schema). Extend this list if new source tables introduce data DLP should look for.
DEFAULT_INFO_TYPES: tuple[str, ...] = (
    "PERSON_NAME",
    "DATE_OF_BIRTH",
    "US_SOCIAL_SECURITY_NUMBER",
    "PHONE_NUMBER",
    "EMAIL_ADDRESS",
    "STREET_ADDRESS",
    "US_HEALTHCARE_NPI",
    "MEDICAL_RECORD_NUMBER",
    "US_STATE",
    "LOCATION",
    "CREDIT_CARD_NUMBER",
)

# infoTypes serious enough that a column containing them should default to PII_LEVEL=HIGH
# when pre-filling the governance tag editor.
_HIGH_SENSITIVITY_INFO_TYPES: frozenset[str] = frozenset(
    {"US_SOCIAL_SECURITY_NUMBER", "DATE_OF_BIRTH", "PERSON_NAME", "MEDICAL_RECORD_NUMBER", "CREDIT_CARD_NUMBER"}
)


@dataclass(slots=True)
class ColumnFinding:
    column: str
    info_type_counts: dict[str, int] = field(default_factory=dict)

    @property
    def recommended_pii_level(self) -> str:
        if not self.info_type_counts:
            return "NONE"
        if _HIGH_SENSITIVITY_INFO_TYPES.intersection(self.info_type_counts):
            return "HIGH"
        return "LOW"


@dataclass(slots=True)
class TableScanResult:
    dataset: str
    table: str
    rows_scanned: int
    columns: list[ColumnFinding]


class DlpScanner:
    """Runs synchronous Cloud DLP content inspection against a sample of a BigQuery table.

    Uses `inspect_content` against a small in-memory sample rather than an async
    `dlpJobs.create` table scan — the latter is built for scheduled, whole-table production
    scanning with results written elsewhere; a synchronous call against a bounded sample is
    a better fit for an interactive "scan this table" button in a UI.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._dlp_client = dlp_v2.DlpServiceClient(credentials=build_credentials(self._settings))
        self._bq_client = build_bigquery_client(self._settings)

    def scan_table(
        self, dataset: str, table: str, sample_size: int = 200, info_types: tuple[str, ...] = DEFAULT_INFO_TYPES
    ) -> TableScanResult:
        table_id = f"{self._settings.gcp_project_id}.{dataset}.{table}"
        result_iterator = self._bq_client.query(f"SELECT * FROM `{table_id}` LIMIT {sample_size}").result()
        column_names = [f.name for f in result_iterator.schema]
        rows = list(result_iterator)

        if not rows:
            return TableScanResult(dataset=dataset, table=table, rows_scanned=0, columns=[])

        headers = [{"name": name} for name in column_names]
        table_rows = [
            {"values": [{"string_value": "" if row[name] is None else str(row[name])} for name in column_names]}
            for row in rows
        ]

        request = {
            "parent": f"projects/{self._settings.gcp_project_id}/locations/global",
            "inspect_config": {
                "info_types": [{"name": t} for t in info_types],
                "min_likelihood": dlp_v2.Likelihood.POSSIBLE,
                "limits": {"max_findings_per_request": 0},
            },
            "item": {"table": {"headers": headers, "rows": table_rows}},
        }
        response = self._dlp_client.inspect_content(request=request)

        counts_by_column: dict[str, Counter[str]] = defaultdict(Counter)
        for finding in response.result.findings:
            if not finding.location.content_locations:
                continue
            column = finding.location.content_locations[0].record_location.field_id.name
            counts_by_column[column][finding.info_type.name] += 1

        columns = [
            ColumnFinding(column=name, info_type_counts=dict(counts_by_column.get(name, {})))
            for name in column_names
        ]
        logger.info(
            "DLP scan of %s.%s: %d rows, %d columns with findings",
            dataset,
            table,
            len(rows),
            sum(1 for c in columns if c.info_type_counts),
        )
        return TableScanResult(dataset=dataset, table=table, rows_scanned=len(rows), columns=columns)
