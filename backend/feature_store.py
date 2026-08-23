from __future__ import annotations

import logging
from dataclasses import dataclass

from google.cloud import bigquery

from config import Settings, build_bigquery_client, get_settings

logger = logging.getLogger(__name__)

FEATURE_TABLE_NAME = "claim_feature_store"

# NOTE: `copay_deductible_ratio` is computed exactly as specified (SUM(copay_applied) /
# SUM(deductible_applied) across a claim's line items). In the current healthcare_insurance
# dataset, `deductible_applied` is 0 for every claim_items row, so this feature evaluates to
# NULL for every claim today. It's left in place — untouched — because it's a data-population
# gap in the source table, not a bug in the feature definition; it will start carrying signal
# the moment deductible_applied is actually populated, with no pipeline changes required.
_FEATURE_STORE_SQL_TEMPLATE = """
CREATE OR REPLACE TABLE `{project}.{dataset}.{feature_table}` AS
WITH claim_item_agg AS (
  SELECT
    claim_id,
    SUM(copay_applied) AS total_copay_applied,
    SUM(deductible_applied) AS total_deductible_applied,
    COUNT(*) AS line_item_count
  FROM `{project}.{dataset}.claim_items`
  GROUP BY claim_id
),
provider_cpt_stats AS (
  -- Each provider's typical billed_charge for a given CPT/HCPCS code, used as the baseline
  -- a claim line's billed_charge is compared against to flag pricing outliers.
  SELECT
    rendering_provider_npi,
    cpt_hcpcs_code,
    AVG(billed_charge) AS avg_billed_charge,
    STDDEV_SAMP(billed_charge) AS stddev_billed_charge
  FROM `{project}.{dataset}.claim_items`
  WHERE rendering_provider_npi IS NOT NULL AND cpt_hcpcs_code IS NOT NULL
  GROUP BY rendering_provider_npi, cpt_hcpcs_code
),
claim_item_z_scores AS (
  SELECT
    ci.claim_id,
    ci.rendering_provider_npi,
    ci.cpt_hcpcs_code,
    SAFE_DIVIDE(ci.billed_charge - s.avg_billed_charge, NULLIF(s.stddev_billed_charge, 0)) AS provider_z_score
  FROM `{project}.{dataset}.claim_items` ci
  JOIN provider_cpt_stats s
    ON ci.rendering_provider_npi = s.rendering_provider_npi
   AND ci.cpt_hcpcs_code = s.cpt_hcpcs_code
),
claim_max_z AS (
  -- Rolls per-line-item z-scores up to one worst-line-item value per claim, since anomaly
  -- scoring and analyst review both operate at the claim grain, not the line-item grain.
  SELECT
    claim_id,
    ARRAY_AGG(
      STRUCT(rendering_provider_npi, cpt_hcpcs_code, provider_z_score)
      ORDER BY ABS(IFNULL(provider_z_score, 0)) DESC
      LIMIT 1
    )[OFFSET(0)] AS worst_line
  FROM claim_item_z_scores
  GROUP BY claim_id
),
member_velocity AS (
  SELECT
    c.claim_id,
    COUNT(c2.claim_id) AS member_claim_velocity
  FROM `{project}.{dataset}.claims` c
  JOIN `{project}.{dataset}.claims` c2
    ON c2.member_id = c.member_id
   AND c2.fnol_received_date
       BETWEEN TIMESTAMP_SUB(c.fnol_received_date, INTERVAL {velocity_window_days} DAY)
       AND c.fnol_received_date
  GROUP BY c.claim_id
)
SELECT
  c.claim_id,
  c.member_id,
  c.plan_id,
  c.claim_type,
  c.claim_status,
  c.service_start_date,
  c.fnol_received_date,
  c.total_billed_amount,
  c.total_allowed_amount,
  c.total_paid_amount,
  SAFE_DIVIDE(c.total_allowed_amount, c.total_billed_amount) AS allowed_to_billed_ratio,
  SAFE_DIVIDE(c.total_paid_amount, c.total_allowed_amount) AS paid_to_allowed_ratio,
  SAFE_DIVIDE(ia.total_copay_applied, ia.total_deductible_applied) AS copay_deductible_ratio,
  IFNULL(ia.line_item_count, 0) AS line_item_count,
  mz.worst_line.provider_z_score AS max_provider_z_score,
  mz.worst_line.rendering_provider_npi AS max_z_provider_npi,
  mz.worst_line.cpt_hcpcs_code AS max_z_cpt_code,
  IFNULL(mv.member_claim_velocity, 1) AS member_claim_velocity,
  CURRENT_TIMESTAMP() AS feature_refreshed_at
FROM `{project}.{dataset}.claims` c
LEFT JOIN claim_item_agg ia ON c.claim_id = ia.claim_id
LEFT JOIN claim_max_z mz ON c.claim_id = mz.claim_id
LEFT JOIN member_velocity mv ON c.claim_id = mv.claim_id
"""

# The subset of claim_feature_store columns that feed IsolationForest training/scoring.
NUMERIC_FEATURE_COLUMNS: tuple[str, ...] = (
    "allowed_to_billed_ratio",
    "paid_to_allowed_ratio",
    "copay_deductible_ratio",
    "line_item_count",
    "max_provider_z_score",
    "member_claim_velocity",
)


@dataclass(slots=True)
class FeatureStoreRefreshResult:
    row_count: int
    table_id: str


class FeatureStoreBuilder:
    """Materializes `claim_feature_store` from raw claims/claim_items via a single BigQuery job.

    A full CREATE OR REPLACE (rather than an incremental MERGE) keeps every refresh idempotent
    and avoids partial-update drift; the dataset is small enough that a full rebuild is cheap.
    """

    def __init__(self, client: bigquery.Client | None = None, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = client or build_bigquery_client(self._settings)

    def refresh(self) -> FeatureStoreRefreshResult:
        sql = _FEATURE_STORE_SQL_TEMPLATE.format(
            project=self._settings.gcp_project_id,
            dataset=self._settings.bigquery_dataset,
            feature_table=FEATURE_TABLE_NAME,
            velocity_window_days=self._settings.member_velocity_window_days,
        )
        logger.info("Refreshing %s...", FEATURE_TABLE_NAME)
        query_job = self._client.query(sql)
        query_job.result()

        table_id = f"{self._settings.gcp_project_id}.{self._settings.bigquery_dataset}.{FEATURE_TABLE_NAME}"
        table = self._client.get_table(table_id)
        logger.info("Refreshed %s: %d rows.", table_id, table.num_rows)
        return FeatureStoreRefreshResult(row_count=table.num_rows, table_id=table_id)
