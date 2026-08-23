export type PiiLevel = "NONE" | "LOW" | "HIGH";

export interface CatalogTableSummary {
  display_name: string;
  dataset: string;
  table: string;
  fully_qualified_name: string;
}

export interface CatalogColumnSchema {
  name: string;
  data_type: string;
  mode: string;
}

export interface GovernanceTag {
  data_owner: string;
  pii_level: PiiLevel;
  retention_days: number;
  notes: string;
}

export interface LinkedGlossaryTerm {
  term_id: string;
  term_display_name: string;
}

export interface CatalogTableDetail {
  display_name: string;
  dataset: string;
  table: string;
  fully_qualified_name: string;
  columns: CatalogColumnSchema[];
  table_tag: GovernanceTag | null;
  column_tags: Record<string, GovernanceTag>;
  table_glossary_link: LinkedGlossaryTerm | null;
  column_glossary_links: Record<string, LinkedGlossaryTerm>;
}

export interface TagUpsertRequest {
  column?: string | null;
  data_owner: string;
  pii_level: PiiLevel;
  retention_days: number;
  notes: string;
  changed_by?: string;
}

export interface GlossaryLinkRequest {
  column?: string | null;
  term_id: string;
  term_display_name: string;
}

export interface AuditEntry {
  audit_id: string;
  column_name: string | null;
  action: "UPSERT" | "DELETE";
  old_value: Record<string, unknown> | null;
  new_value: Record<string, unknown> | null;
  changed_by: string;
  changed_at: string;
}

export interface AuditHistoryResponse {
  entries: AuditEntry[];
}

export interface TagUpsertResult {
  status: "APPLIED" | "PENDING_APPROVAL";
  detail: CatalogTableDetail | null;
  approval_id: string | null;
  message: string;
}

export type RestrictionLevel = "HIGH" | "LOW";

export interface AccessRestrictionResponse {
  dataset: string;
  table: string;
  column: string;
  level: RestrictionLevel | null;
  readers: string[];
}

export interface PendingApproval {
  approval_id: string;
  dataset: string;
  table_name: string;
  column_name: string | null;
  action: "UPSERT" | "DELETE";
  proposed_data: Record<string, unknown> | null;
  status: "PENDING" | "APPROVED" | "REJECTED";
  proposed_by: string;
  proposed_at: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
}

export interface GlossaryTerm {
  term_id: string;
  display_name: string;
  description: string;
}

export interface PiiColumnFinding {
  column: string;
  info_type_counts: Record<string, number>;
  recommended_pii_level: PiiLevel;
}

export interface PiiScanResponse {
  dataset: string;
  table: string;
  rows_scanned: number;
  columns: PiiColumnFinding[];
}

export interface DataProfileFieldProfile {
  name: string;
  type: string;
  profile?: {
    distinctRatio?: number;
    nullRatio?: number;
    stringProfile?: { averageLength?: number; minLength?: string; maxLength?: string };
  };
}

export interface DataProfileResponse {
  state: string;
  rows_scanned: number | null;
  fields: DataProfileFieldProfile[];
}

export interface LineageNode {
  table: string;
}

export interface LineageEdge {
  source: string;
  target: string;
  description: string;
}

export interface LineageResponse {
  nodes: LineageNode[];
  edges: LineageEdge[];
}

export type QualityDimension = "COMPLETENESS" | "UNIQUENESS" | "VALIDITY" | "ACCURACY" | "CONSISTENCY" | "TIMELINESS";
export type QualityRuleType = "non_null" | "unique" | "range" | "regex" | "set";

export interface QualityRuleRequest {
  column: string;
  dimension: QualityDimension;
  rule_type: QualityRuleType;
  threshold?: number;
  min_value?: string | null;
  max_value?: string | null;
  regex?: string | null;
  set_values?: string[] | null;
}

export interface QualityRule extends QualityRuleRequest {
  index: number;
}

export interface QualityRuleListResponse {
  rules: QualityRule[];
}

export interface QualityRuleResultItem {
  column: string;
  dimension: string;
  passed: boolean;
  pass_ratio: number;
  passed_count: number;
  evaluated_count: number;
  failing_rows_query: string | null;
}

export interface QualityScanResponse {
  state: string;
  passed: boolean | null;
  score: number | null;
  row_count: number | null;
  rules: QualityRuleResultItem[];
}

export class CatalogApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "CatalogApiError";
    this.status = status;
  }
}
