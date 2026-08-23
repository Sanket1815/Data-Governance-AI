export type ReviewStatus = "PENDING_REVIEW" | "CONFIRMED_FRAUD" | "FALSE_POSITIVE" | "CLEARED";

export type PipelineRunStatus = "RUNNING" | "SUCCESS" | "FAILED";

export interface PipelineRunResponse {
  run_id: string;
  status: string;
  message: string;
}

export interface PipelineRunLogEntry {
  run_id: string;
  started_at: string;
  completed_at: string | null;
  status: PipelineRunStatus;
  total_claims_scored: number | null;
  anomalies_flagged: number | null;
  error_message: string | null;
  model_artifact_uri: string | null;
}

export interface RiskScoreBucket {
  bucket_start: number;
  bucket_end: number;
  count: number;
}

export interface MetricsResponse {
  total_claims: number;
  total_anomalies: number;
  anomaly_rate: number;
  review_status_counts: Record<string, number>;
  risk_score_distribution: RiskScoreBucket[];
  latest_run: PipelineRunLogEntry | null;
  recent_runs: PipelineRunLogEntry[];
}

export interface RiskDriver {
  feature: string;
  value: number;
  shap_value: number;
  description: string;
}

export interface ClaimReviewItem {
  claim_id: string;
  member_id: string;
  plan_id: string;
  claim_type: string;
  claim_status: string;
  service_start_date: string;
  total_billed_amount: number;
  total_allowed_amount: number;
  total_paid_amount: number;
  anomaly_risk_score: number;
  is_anomaly: number;
  top_risk_drivers: RiskDriver[];
  review_status: ReviewStatus;
  scored_at: string;
}

export interface ClaimReviewResponse {
  items: ClaimReviewItem[];
  total_count: number;
}

export interface ClaimStatusUpdateResponse {
  claim_id: string;
  review_status: ReviewStatus;
  reviewed_at: string | null;
}

export class AnomalyApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "AnomalyApiError";
    this.status = status;
  }
}
