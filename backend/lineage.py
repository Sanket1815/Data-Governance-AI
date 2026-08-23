from __future__ import annotations

from dataclasses import dataclass

# GCP's own Data Lineage API is disabled on this project and, even enabled, only captures
# lineage automatically for query patterns it recognizes — it's not guaranteed to pick up
# CREATE OR REPLACE TABLE AS SELECT or MERGE jobs the way it does plain SELECT-based ones.
# Rather than depend on that, this graph is derived directly from the pipeline this app
# actually runs (feature_store.py + batch_pipeline.py) — it's a small, accurate, hand-verified
# DAG rather than an automatically-discovered one, and only covers the tables this app derives;
# it does not attempt to describe the wider dataset's structure.


@dataclass(slots=True)
class LineageEdge:
    source_table: str
    target_table: str
    description: str


PIPELINE_LINEAGE: tuple[LineageEdge, ...] = (
    LineageEdge(
        "claims",
        "claim_feature_store",
        "Per-claim ratios, member 30-day claim velocity",
    ),
    LineageEdge(
        "claim_items",
        "claim_feature_store",
        "Line-item billed charges baselined per (provider, CPT code) into provider_z_score",
    ),
    LineageEdge(
        "claim_feature_store",
        "claim_anomaly_results_staging",
        "IsolationForest training + SHAP-explained scoring (batch_pipeline.py)",
    ),
    LineageEdge(
        "claim_anomaly_results_staging",
        "claim_anomaly_results",
        "MERGE upsert: refreshes score/model_version, preserves analyst review_status",
    ),
)


def get_pipeline_lineage() -> dict[str, list[dict[str, str]]]:
    nodes = sorted({edge.source_table for edge in PIPELINE_LINEAGE} | {edge.target_table for edge in PIPELINE_LINEAGE})
    return {
        "nodes": [{"table": n} for n in nodes],
        "edges": [
            {"source": e.source_table, "target": e.target_table, "description": e.description}
            for e in PIPELINE_LINEAGE
        ],
    }
