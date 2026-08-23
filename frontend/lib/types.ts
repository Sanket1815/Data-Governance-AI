export interface QueryResponseData {
  columns: string[];
  rows: Record<string, unknown>[];
}

export interface NL2SQLResponse {
  sql: string;
  execution_time_ms: number;
  estimated_bytes: number;
  data: QueryResponseData;
  cache_hit: boolean;
  used_fallback_model: boolean;
  attempts: number;
}

export interface NL2SQLErrorPayload {
  detail: string;
}

export class NL2SQLApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "NL2SQLApiError";
    this.status = status;
  }
}
