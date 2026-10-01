from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Literal

from google.auth.credentials import Credentials
from google.cloud import bigquery
from google.oauth2 import service_account
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central environment-driven configuration. All values are overridable via env vars or .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- GCP / BigQuery ---
    gcp_project_id: str = Field(default="project-d60256f0-58d4-461d-86f", alias="GCP_PROJECT_ID")
    bigquery_dataset: str = Field(default="healthcare_insurance", alias="BIGQUERY_DATASET")
    gcp_location: str = Field(default="US", alias="GCP_LOCATION")
    google_application_credentials: str | None = Field(default=None, alias="GOOGLE_APPLICATION_CREDENTIALS")

    # --- LLM provider selection ---
    llm_provider: Literal["gemini", "openai"] = Field(default="gemini", alias="LLM_PROVIDER")

    # Gemini
    google_api_key: str | None = Field(default=None, alias="GOOGLE_API_KEY")
    gemini_primary_model: str = Field(default="gemini-flash-latest", alias="GEMINI_PRIMARY_MODEL")
    gemini_fallback_model: str = Field(default="gemini-pro-latest", alias="GEMINI_FALLBACK_MODEL")

    # OpenAI (alternate provider)
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_primary_model: str = Field(default="gpt-4o-mini", alias="OPENAI_PRIMARY_MODEL")
    openai_fallback_model: str = Field(default="gpt-4o", alias="OPENAI_FALLBACK_MODEL")

    embedding_model: str = Field(default="gemini-embedding-001", alias="EMBEDDING_MODEL")

    # --- Redis semantic cache ---
    redis_url: str = Field(default="redis://localhost:6379", alias="REDIS_URL")
    redis_cache_ttl_seconds: int = Field(default=3600, alias="REDIS_CACHE_TTL_SECONDS")
    semantic_cache_distance_threshold: float = Field(default=0.1, alias="SEMANTIC_CACHE_DISTANCE_THRESHOLD")

    # --- Query engine tuning ---
    table_retriever_top_k: int = Field(default=3, alias="TABLE_RETRIEVER_TOP_K")
    self_healing_max_retries: int = Field(default=3, alias="SELF_HEALING_MAX_RETRIES")
    max_bytes_billed: int = Field(default=1_073_741_824, alias="MAX_BYTES_BILLED")  # 1 GB
    query_result_row_limit: int = Field(default=1000, alias="QUERY_RESULT_ROW_LIMIT")

    # --- API ---
    api_cors_origins: list[str] = Field(default=["http://localhost:3000"], alias="API_CORS_ORIGINS")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # --- Anomaly / Feature Store engine ---
    gcs_artifact_bucket: str = Field(
        default="project-d60256f0-58d4-461d-86f-fwa-artifacts", alias="GCS_ARTIFACT_BUCKET"
    )
    anomaly_contamination: float = Field(default=0.03, alias="ANOMALY_CONTAMINATION")
    anomaly_random_state: int = Field(default=42, alias="ANOMALY_RANDOM_STATE")
    anomaly_review_score_threshold: float = Field(default=70.0, alias="ANOMALY_REVIEW_SCORE_THRESHOLD")
    member_velocity_window_days: int = Field(default=30, alias="MEMBER_VELOCITY_WINDOW_DAYS")

    # --- Data Governance Catalog (Dataplex) ---
    dataplex_location: str = Field(default="us", alias="DATAPLEX_LOCATION")
    dataplex_datascan_location: str = Field(default="us-central1", alias="DATAPLEX_DATASCAN_LOCATION")
    dataplex_entry_group: str = Field(default="@bigquery", alias="DATAPLEX_ENTRY_GROUP")
    dataplex_glossary_id: str = Field(default="data-governance-glossary", alias="DATAPLEX_GLOSSARY_ID")
    dataplex_governance_aspect_type_id: str = Field(
        default="data-governance-tag", alias="DATAPLEX_GOVERNANCE_ASPECT_TYPE_ID"
    )
    dataplex_glossary_link_aspect_type_id: str = Field(
        default="glossary-term-link", alias="DATAPLEX_GLOSSARY_LINK_ASPECT_TYPE_ID"
    )
    catalog_audit_log_table: str = Field(default="catalog_tag_audit_log", alias="CATALOG_AUDIT_LOG_TABLE")

    # --- Real column-level access enforcement (BigQuery Policy Tags via Data Catalog) ---
    access_control_location: str = Field(default="us", alias="ACCESS_CONTROL_LOCATION")
    access_control_taxonomy_name: str = Field(
        default="data-governance-pii-taxonomy", alias="ACCESS_CONTROL_TAXONOMY_NAME"
    )
    catalog_pending_approvals_table: str = Field(
        default="catalog_pending_approvals", alias="CATALOG_PENDING_APPROVALS_TABLE"
    )

    @field_validator("max_bytes_billed")
    @classmethod
    def _positive_byte_cap(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("max_bytes_billed must be a positive integer")
        return v

    @property
    def bigquery_connection_string(self) -> str:
        return f"bigquery://{self.gcp_project_id}/{self.bigquery_dataset}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def build_credentials(settings: Settings | None = None) -> Credentials | None:
    """Explicitly resolves credentials from GOOGLE_APPLICATION_CREDENTIALS in .env.

    google-auth's implicit `Client()` resolution reads the raw OS environment variable
    directly, which can silently pick up an unrelated ambient value set elsewhere on the
    machine and ignore what's configured in .env. Loading the file explicitly here makes
    .env authoritative and fails loudly if the configured path is wrong, instead of quietly
    authenticating as the wrong principal.
    """
    settings = settings or get_settings()
    if not settings.google_application_credentials:
        return None

    credentials_path = Path(settings.google_application_credentials)
    if not credentials_path.is_file():
        # On Cloud Run the runtime service account provides ADC; a stale local path in env is common.
        logging.getLogger(__name__).warning(
            "GOOGLE_APPLICATION_CREDENTIALS points to a missing file (%s); using Application Default Credentials.",
            credentials_path,
        )
        return None
    return service_account.Credentials.from_service_account_file(str(credentials_path))


def build_bigquery_client(settings: Settings | None = None) -> bigquery.Client:
    settings = settings or get_settings()
    credentials = build_credentials(settings)
    return bigquery.Client(project=settings.gcp_project_id, credentials=credentials)
