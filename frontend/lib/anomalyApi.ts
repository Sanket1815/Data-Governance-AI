import {
  AnomalyApiError,
  ClaimReviewResponse,
  ClaimStatusUpdateResponse,
  MetricsResponse,
  PipelineRunResponse,
  ReviewStatus,
} from "./anomalyTypes";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      // response body was not JSON; fall back to the generic status message
    }
    throw new AnomalyApiError(detail, response.status);
  }
  return (await response.json()) as T;
}

export async function triggerPipelineRun(signal?: AbortSignal): Promise<PipelineRunResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/pipeline/run`, { method: "POST", signal });
  return handleResponse<PipelineRunResponse>(response);
}

export async function getMetrics(signal?: AbortSignal): Promise<MetricsResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/metrics`, { signal });
  return handleResponse<MetricsResponse>(response);
}

export interface ClaimsReviewParams {
  reviewStatus?: ReviewStatus;
  minScore?: number;
  limit?: number;
  offset?: number;
}

export async function getClaimsForReview(
  params: ClaimsReviewParams = {},
  signal?: AbortSignal
): Promise<ClaimReviewResponse> {
  const searchParams = new URLSearchParams();
  if (params.reviewStatus) searchParams.set("review_status", params.reviewStatus);
  if (params.minScore !== undefined) searchParams.set("min_score", String(params.minScore));
  if (params.limit !== undefined) searchParams.set("limit", String(params.limit));
  if (params.offset !== undefined) searchParams.set("offset", String(params.offset));

  const response = await fetch(`${API_BASE_URL}/api/v1/claims/review?${searchParams.toString()}`, { signal });
  return handleResponse<ClaimReviewResponse>(response);
}

export async function updateClaimStatus(
  claimId: string,
  reviewStatus: ReviewStatus,
  signal?: AbortSignal
): Promise<ClaimStatusUpdateResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/claims/${encodeURIComponent(claimId)}/status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ review_status: reviewStatus }),
    signal,
  });
  return handleResponse<ClaimStatusUpdateResponse>(response);
}

export function formatCurrency(value: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(value);
}

export function formatTimestamp(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
