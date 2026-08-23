"use client";

import { AlertTriangle, DatabaseZap } from "lucide-react";
import { useCallback, useRef, useState } from "react";
import ResultsTable from "@/components/ResultsTable";
import SearchBar from "@/components/SearchBar";
import SqlViewer from "@/components/SqlViewer";
import { runNl2SqlQuery } from "@/lib/api";
import { NL2SQLApiError, NL2SQLResponse } from "@/lib/types";

export default function Home() {
  const [result, setResult] = useState<NL2SQLResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);

  const handleSubmit = useCallback(async (prompt: string) => {
    abortControllerRef.current?.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;

    setIsLoading(true);
    setError(null);

    try {
      const response = await runNl2SqlQuery(prompt, controller.signal);
      setResult(response);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      const message = err instanceof NL2SQLApiError ? err.message : "Something went wrong while running your query.";
      setError(message);
      setResult(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  return (
    <main className="mx-auto flex min-h-screen max-w-4xl flex-col px-6 py-16">
      <header className="mb-10 flex flex-col items-center text-center">
        <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl bg-indigo-500/15">
          <DatabaseZap className="h-5 w-5 text-indigo-400" aria-hidden="true" />
        </div>
        <h1 className="text-2xl font-semibold text-gray-100">Ask your BigQuery data anything</h1>
        <p className="mt-2 max-w-lg text-sm text-gray-500">
          Natural language queries over the <code className="text-gray-400">healthcare_insurance</code> dataset,
          translated to validated GoogleSQL.
        </p>
      </header>

      <SearchBar onSubmit={handleSubmit} isLoading={isLoading} />

      <div className="mt-8 flex flex-col gap-6">
        {error && (
          <div className="flex items-start gap-3 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <span>{error}</span>
          </div>
        )}

        {isLoading && !result && (
          <div className="animate-fade-in space-y-3">
            <div className="h-32 animate-pulse rounded-xl border border-surface-border bg-surface-raised" />
            <div className="h-48 animate-pulse rounded-xl border border-surface-border bg-surface-raised" />
          </div>
        )}

        {result && (
          <div className="animate-fade-in space-y-6">
            <SqlViewer sql={result.sql} usedFallbackModel={result.used_fallback_model} />
            <ResultsTable
              columns={result.data.columns}
              rows={result.data.rows}
              estimatedBytes={result.estimated_bytes}
              executionTimeMs={result.execution_time_ms}
              cacheHit={result.cache_hit}
            />
          </div>
        )}
      </div>
    </main>
  );
}
