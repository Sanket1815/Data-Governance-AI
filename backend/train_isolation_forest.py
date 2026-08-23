from __future__ import annotations

import json
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import shap
from google.cloud import bigquery, storage
from sklearn.ensemble import IsolationForest

from config import Settings, build_bigquery_client, build_credentials, get_settings
from feature_store import FEATURE_TABLE_NAME, NUMERIC_FEATURE_COLUMNS

logger = logging.getLogger(__name__)

# Human-readable templates for SHAP-driven root-cause explanations, matching the analyst-facing
# badge style (e.g. "High Provider Z-Score (+3.8)", "Member Velocity High (14/30d)").
_FEATURE_DESCRIPTION_TEMPLATES: dict[str, str] = {
    "max_provider_z_score": "High Provider Z-Score ({value:+.1f})",
    "member_claim_velocity": "Member Velocity High ({value:.0f}/30d)",
    "allowed_to_billed_ratio": "Unusual Allowed-to-Billed Ratio ({value:.2f})",
    "paid_to_allowed_ratio": "Unusual Paid-to-Allowed Ratio ({value:.2f})",
    "copay_deductible_ratio": "Unusual Copay/Deductible Ratio ({value:.2f})",
    "line_item_count": "Unusual Line Item Count ({value:.0f})",
}


@dataclass(slots=True)
class TrainingResult:
    model: IsolationForest
    feature_columns: list[str]
    impute_values: dict[str, float]
    training_row_count: int


@dataclass(slots=True)
class ScoringResult:
    scored_df: pd.DataFrame  # columns: claim_id, anomaly_risk_score, is_anomaly, top_risk_drivers
    anomaly_count: int


class IsolationForestTrainer:
    """Trains an IsolationForest over `claim_feature_store` and produces SHAP-explained anomaly scores."""

    def __init__(self, client: bigquery.Client | None = None, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._client = client or build_bigquery_client(self._settings)

    def load_features(self) -> pd.DataFrame:
        table_id = f"{self._settings.gcp_project_id}.{self._settings.bigquery_dataset}.{FEATURE_TABLE_NAME}"
        logger.info("Loading features from %s...", table_id)
        df = self._client.query(f"SELECT * FROM `{table_id}`").to_dataframe()
        logger.info("Loaded %d feature rows.", len(df))
        return df

    def train(self, df: pd.DataFrame) -> TrainingResult:
        feature_columns = list(NUMERIC_FEATURE_COLUMNS)
        X, impute_values = self._prepare_matrix(df, feature_columns)

        model = IsolationForest(
            contamination=self._settings.anomaly_contamination,
            random_state=self._settings.anomaly_random_state,
        )
        model.fit(X)
        return TrainingResult(
            model=model,
            feature_columns=feature_columns,
            impute_values=impute_values,
            training_row_count=len(X),
        )

    def score(self, df: pd.DataFrame, training: TrainingResult) -> ScoringResult:
        X, _ = self._prepare_matrix(df, training.feature_columns, impute_values=training.impute_values)

        raw_scores = training.model.score_samples(X)  # lower == more anomalous
        min_score, max_score = float(raw_scores.min()), float(raw_scores.max())
        score_range = max_score - min_score
        if score_range == 0:
            risk_scores = np.zeros(len(raw_scores))
        else:
            risk_scores = 100.0 * (max_score - raw_scores) / score_range

        is_anomaly = training.model.predict(X)  # -1 (anomaly) or 1 (normal)

        explainer = shap.TreeExplainer(training.model)
        shap_values = np.asarray(explainer.shap_values(X))

        top_drivers = [
            self._top_drivers_for_row(X.iloc[i], shap_values[i], training.feature_columns)
            for i in range(len(X))
        ]

        scored_df = pd.DataFrame(
            {
                "claim_id": df["claim_id"].values,
                "anomaly_risk_score": np.round(risk_scores, 2),
                "is_anomaly": is_anomaly.astype(int),
                "top_risk_drivers": [json.dumps(d) for d in top_drivers],
            }
        )
        anomaly_count = int((is_anomaly == -1).sum())
        return ScoringResult(scored_df=scored_df, anomaly_count=anomaly_count)

    def save_artifact(self, training: TrainingResult, run_id: str) -> str:
        """Serializes the trained model + preprocessing state to GCS and returns its gs:// URI."""
        bundle = {
            "model": training.model,
            "feature_columns": training.feature_columns,
            "impute_values": training.impute_values,
            "contamination": self._settings.anomaly_contamination,
            "random_state": self._settings.anomaly_random_state,
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            local_path = Path(tmp_dir) / f"isolation_forest_{run_id}.joblib"
            joblib.dump(bundle, local_path)

            storage_client = storage.Client(
                project=self._settings.gcp_project_id, credentials=build_credentials(self._settings)
            )
            bucket = storage_client.bucket(self._settings.gcs_artifact_bucket)
            blob_name = f"models/isolation_forest_{run_id}.joblib"
            blob = bucket.blob(blob_name)
            blob.upload_from_filename(str(local_path))

        gcs_uri = f"gs://{self._settings.gcs_artifact_bucket}/{blob_name}"
        logger.info("Saved model artifact to %s", gcs_uri)
        return gcs_uri

    @staticmethod
    def _prepare_matrix(
        df: pd.DataFrame,
        feature_columns: list[str],
        impute_values: dict[str, float] | None = None,
    ) -> tuple[pd.DataFrame, dict[str, float]]:
        X = df[feature_columns].astype(float).copy()
        resolved_impute_values = dict(impute_values or {})
        for column in feature_columns:
            if column not in resolved_impute_values:
                median = X[column].median()
                resolved_impute_values[column] = 0.0 if pd.isna(median) else float(median)
            X[column] = X[column].fillna(resolved_impute_values[column])
        return X, resolved_impute_values

    @staticmethod
    def _top_drivers_for_row(
        row: pd.Series, shap_row: np.ndarray, feature_columns: list[str], top_n: int = 3
    ) -> list[dict]:
        order = np.argsort(-np.abs(shap_row))[:top_n]
        drivers = []
        for idx in order:
            feature = feature_columns[idx]
            value = float(row[feature])
            template = _FEATURE_DESCRIPTION_TEMPLATES.get(feature, feature + " ({value:.2f})")
            drivers.append(
                {
                    "feature": feature,
                    "value": value,
                    "shap_value": round(float(shap_row[idx]), 4),
                    "description": template.format(value=value),
                }
            )
        return drivers
