"use client";

import { History, Loader2, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { getTagHistory } from "@/lib/catalogApi";
import { AuditEntry, CatalogApiError } from "@/lib/catalogTypes";

interface CatalogAuditHistoryProps {
  dataset: string;
  table: string;
}

function formatTimestamp(value: string): string {
  return new Date(value).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function diffSummary(entry: AuditEntry): string {
  if (entry.action === "DELETE") return "removed the tag";
  if (!entry.old_value) return "created the tag";
  const changed: string[] = [];
  const oldVal = entry.old_value;
  const newVal = entry.new_value ?? {};
  for (const key of Object.keys(newVal)) {
    if (JSON.stringify(oldVal[key]) !== JSON.stringify(newVal[key])) {
      changed.push(key);
    }
  }
  return changed.length ? `changed ${changed.join(", ")}` : "saved with no changes";
}

export default function CatalogAuditHistory({ dataset, table }: CatalogAuditHistoryProps) {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isOpen, setIsOpen] = useState(false);

  const load = useCallback(() => {
    setIsLoading(true);
    getTagHistory(dataset, table)
      .then((res) => setEntries(res.entries))
      .catch((err) => setError(err instanceof CatalogApiError ? err.message : "Failed to load history."))
      .finally(() => setIsLoading(false));
  }, [dataset, table]);

  useEffect(() => {
    setIsOpen(false);
    setEntries([]);
  }, [dataset, table]);

  useEffect(() => {
    if (isOpen) load();
  }, [isOpen, load]);

  return (
    <div className="rounded-xl border border-surface-border bg-surface-raised p-4">
      <button
        type="button"
        onClick={() => setIsOpen((v) => !v)}
        className="flex w-full items-center justify-between text-left"
      >
        <span className="flex items-center gap-2 text-sm font-medium text-gray-300">
          <History className="h-4 w-4 text-gray-400" />
          Tag change history
        </span>
        <span className="text-xs text-gray-500">{isOpen ? "hide" : "show"}</span>
      </button>

      {isOpen && (
        <div className="mt-3 border-t border-surface-border pt-3">
          <div className="mb-2 flex justify-end">
            <button
              type="button"
              onClick={load}
              disabled={isLoading}
              className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-gray-500 hover:bg-white/5 hover:text-gray-300"
            >
              {isLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
              Refresh
            </button>
          </div>

          {error && <p className="text-xs text-red-400">{error}</p>}

          {!isLoading && entries.length === 0 && !error && (
            <p className="text-xs text-gray-600">No tag changes recorded for this table yet.</p>
          )}

          <ul className="space-y-1.5">
            {entries.map((entry) => (
              <li key={entry.audit_id} className="rounded-lg bg-white/[0.03] px-3 py-2 text-xs">
                <div className="flex items-center justify-between">
                  <span className="text-gray-300">
                    <span className="font-medium text-gray-100">{entry.changed_by || "unknown"}</span>{" "}
                    {diffSummary(entry)}
                    {entry.column_name && (
                      <>
                        {" "}
                        on <span className="font-mono text-gray-400">{entry.column_name}</span>
                      </>
                    )}
                  </span>
                  <span className="shrink-0 text-gray-600">{formatTimestamp(entry.changed_at)}</span>
                </div>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[10.5px] text-gray-600">
            "Changed by" is self-reported free text — this app has no authentication system, so it isn't a verified
            identity.
          </p>
        </div>
      )}
    </div>
  );
}
