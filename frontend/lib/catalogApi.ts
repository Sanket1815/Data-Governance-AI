import {
  AccessRestrictionResponse,
  AuditHistoryResponse,
  CatalogApiError,
  CatalogTableDetail,
  CatalogTableSummary,
  DataProfileResponse,
  GlossaryLinkRequest,
  GlossaryTerm,
  LineageResponse,
  PendingApproval,
  PiiScanResponse,
  QualityRuleListResponse,
  QualityRuleRequest,
  QualityScanResponse,
  TagUpsertRequest,
  TagUpsertResult,
} from "./catalogTypes";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`;
    try {
      const body = await response.json();
      if (Array.isArray(body.detail)) {
        // FastAPI/Pydantic validation errors (422) come back as a list of error objects.
        detail = body.detail.map((e: { msg?: string }) => e.msg ?? JSON.stringify(e)).join("; ");
      } else if (typeof body.detail === "string") {
        detail = body.detail;
      }
    } catch {
      // response body was not JSON; fall back to the generic status message
    }
    throw new CatalogApiError(detail, response.status);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function listTables(dataset = "healthcare_insurance"): Promise<CatalogTableSummary[]> {
  const response = await fetch(`${API_BASE_URL}/api/v1/catalog/tables?dataset=${encodeURIComponent(dataset)}`);
  return handleResponse<CatalogTableSummary[]>(response);
}

export async function searchCatalog(query: string): Promise<CatalogTableSummary[]> {
  const response = await fetch(`${API_BASE_URL}/api/v1/catalog/search?q=${encodeURIComponent(query)}`);
  return handleResponse<CatalogTableSummary[]>(response);
}

export async function getTableDetail(dataset: string, table: string): Promise<CatalogTableDetail> {
  const response = await fetch(`${API_BASE_URL}/api/v1/catalog/tables/${dataset}/${table}`);
  return handleResponse<CatalogTableDetail>(response);
}

export async function upsertTag(dataset: string, table: string, request: TagUpsertRequest): Promise<TagUpsertResult> {
  const response = await fetch(`${API_BASE_URL}/api/v1/catalog/tables/${dataset}/${table}/tags`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  return handleResponse<TagUpsertResult>(response);
}

export async function deleteTag(
  dataset: string,
  table: string,
  column?: string | null,
  changedBy?: string
): Promise<TagUpsertResult> {
  const params = new URLSearchParams();
  if (column) params.set("column", column);
  if (changedBy) params.set("changed_by", changedBy);
  const query = params.toString();
  const response = await fetch(`${API_BASE_URL}/api/v1/catalog/tables/${dataset}/${table}/tags${query ? `?${query}` : ""}`, {
    method: "DELETE",
  });
  return handleResponse<TagUpsertResult>(response);
}

export async function getTagHistory(dataset: string, table: string, limit = 50): Promise<AuditHistoryResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/catalog/tables/${dataset}/${table}/tags/history?limit=${limit}`);
  return handleResponse<AuditHistoryResponse>(response);
}

export async function linkGlossaryTerm(
  dataset: string,
  table: string,
  request: GlossaryLinkRequest
): Promise<CatalogTableDetail> {
  const response = await fetch(`${API_BASE_URL}/api/v1/catalog/tables/${dataset}/${table}/glossary-link`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  return handleResponse<CatalogTableDetail>(response);
}

export async function unlinkGlossaryTerm(
  dataset: string,
  table: string,
  column?: string | null
): Promise<CatalogTableDetail> {
  const params = column ? `?column=${encodeURIComponent(column)}` : "";
  const response = await fetch(`${API_BASE_URL}/api/v1/catalog/tables/${dataset}/${table}/glossary-link${params}`, {
    method: "DELETE",
  });
  return handleResponse<CatalogTableDetail>(response);
}

export async function listGlossaryTerms(): Promise<GlossaryTerm[]> {
  const response = await fetch(`${API_BASE_URL}/api/v1/catalog/glossary`);
  return handleResponse<GlossaryTerm[]>(response);
}

export async function createGlossaryTerm(termId: string, displayName: string, description: string): Promise<GlossaryTerm> {
  const response = await fetch(`${API_BASE_URL}/api/v1/catalog/glossary`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ term_id: termId, display_name: displayName, description }),
  });
  return handleResponse<GlossaryTerm>(response);
}

export async function deleteGlossaryTerm(termId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/v1/catalog/glossary/${encodeURIComponent(termId)}`, {
    method: "DELETE",
  });
  await handleResponse<void>(response);
}

export async function scanTableForPii(dataset: string, table: string, sampleSize = 200): Promise<PiiScanResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/v1/catalog/tables/${dataset}/${table}/pii-scan?sample_size=${sampleSize}`,
    { method: "POST" }
  );
  return handleResponse<PiiScanResponse>(response);
}

export async function triggerProfileScan(dataset: string, table: string): Promise<{ job_id: string; status: string }> {
  const response = await fetch(`${API_BASE_URL}/api/v1/catalog/tables/${dataset}/${table}/profile`, {
    method: "POST",
  });
  return handleResponse<{ job_id: string; status: string }>(response);
}

export async function getProfileResult(dataset: string, table: string): Promise<DataProfileResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/catalog/tables/${dataset}/${table}/profile`);
  return handleResponse<DataProfileResponse>(response);
}

export async function getLineage(): Promise<LineageResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/catalog/lineage`);
  return handleResponse<LineageResponse>(response);
}

export async function listQualityRules(dataset: string, table: string): Promise<QualityRuleListResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/catalog/tables/${dataset}/${table}/quality/rules`);
  return handleResponse<QualityRuleListResponse>(response);
}

export async function addQualityRule(
  dataset: string,
  table: string,
  rule: QualityRuleRequest
): Promise<QualityRuleListResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/catalog/tables/${dataset}/${table}/quality/rules`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(rule),
  });
  return handleResponse<QualityRuleListResponse>(response);
}

export async function deleteQualityRule(dataset: string, table: string, index: number): Promise<QualityRuleListResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/catalog/tables/${dataset}/${table}/quality/rules/${index}`, {
    method: "DELETE",
  });
  return handleResponse<QualityRuleListResponse>(response);
}

export async function triggerQualityScan(dataset: string, table: string): Promise<{ job_id: string; status: string }> {
  const response = await fetch(`${API_BASE_URL}/api/v1/catalog/tables/${dataset}/${table}/quality/run`, {
    method: "POST",
  });
  return handleResponse<{ job_id: string; status: string }>(response);
}

export async function getQualityResult(dataset: string, table: string): Promise<QualityScanResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/catalog/tables/${dataset}/${table}/quality/result`);
  return handleResponse<QualityScanResponse>(response);
}

export async function getColumnAccess(dataset: string, table: string, column: string): Promise<AccessRestrictionResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/catalog/tables/${dataset}/${table}/access/${encodeURIComponent(column)}`);
  return handleResponse<AccessRestrictionResponse>(response);
}

export async function grantColumnReader(
  dataset: string,
  table: string,
  column: string,
  principal: string
): Promise<AccessRestrictionResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/v1/catalog/tables/${dataset}/${table}/access/${encodeURIComponent(column)}/readers`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ principal }),
    }
  );
  return handleResponse<AccessRestrictionResponse>(response);
}

export async function revokeColumnReader(
  dataset: string,
  table: string,
  column: string,
  principal: string
): Promise<AccessRestrictionResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/v1/catalog/tables/${dataset}/${table}/access/${encodeURIComponent(column)}/readers?principal=${encodeURIComponent(principal)}`,
    { method: "DELETE" }
  );
  return handleResponse<AccessRestrictionResponse>(response);
}

export async function listPendingApprovals(): Promise<PendingApproval[]> {
  const response = await fetch(`${API_BASE_URL}/api/v1/catalog/approvals`);
  return handleResponse<PendingApproval[]>(response);
}

export async function approveChange(approvalId: string, reviewedBy: string): Promise<PendingApproval> {
  const response = await fetch(`${API_BASE_URL}/api/v1/catalog/approvals/${approvalId}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reviewed_by: reviewedBy }),
  });
  return handleResponse<PendingApproval>(response);
}

export async function rejectChange(approvalId: string, reviewedBy: string): Promise<PendingApproval> {
  const response = await fetch(`${API_BASE_URL}/api/v1/catalog/approvals/${approvalId}/reject`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reviewed_by: reviewedBy }),
  });
  return handleResponse<PendingApproval>(response);
}
