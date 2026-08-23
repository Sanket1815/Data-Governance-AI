import { NL2SQLApiError, NL2SQLErrorPayload, NL2SQLResponse } from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

export async function runNl2SqlQuery(userPrompt: string, signal?: AbortSignal): Promise<NL2SQLResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_prompt: userPrompt }),
    signal,
  });

  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`;
    try {
      const errorPayload = (await response.json()) as NL2SQLErrorPayload;
      detail = errorPayload.detail ?? detail;
    } catch {
      // response body was not JSON; fall back to the generic status message
    }
    throw new NL2SQLApiError(detail, response.status);
  }

  return (await response.json()) as NL2SQLResponse;
}

export function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** exponent;
  return `${value.toFixed(value >= 10 || exponent === 0 ? 0 : 1)} ${units[exponent]}`;
}

export function formatLatency(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}
