"use client";

import { ArrowUpDown, ChevronLeft, ChevronRight, Clock, Database, Zap } from "lucide-react";
import { useMemo, useState } from "react";
import clsx from "clsx";
import { formatBytes, formatLatency } from "@/lib/api";

interface ResultsTableProps {
  columns: string[];
  rows: Record<string, unknown>[];
  estimatedBytes: number;
  executionTimeMs: number;
  cacheHit: boolean;
}

type SortDirection = "asc" | "desc";

const PAGE_SIZE = 10;

function formatCellValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export default function ResultsTable({ columns, rows, estimatedBytes, executionTimeMs, cacheHit }: ResultsTableProps) {
  const [sortColumn, setSortColumn] = useState<string | null>(null);
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");
  const [page, setPage] = useState(0);

  const sortedRows = useMemo(() => {
    if (!sortColumn) return rows;
    const copy = [...rows];
    copy.sort((a, b) => {
      const aVal = a[sortColumn];
      const bVal = b[sortColumn];
      if (aVal === bVal) return 0;
      if (aVal === null || aVal === undefined) return 1;
      if (bVal === null || bVal === undefined) return -1;

      const comparison =
        typeof aVal === "number" && typeof bVal === "number"
          ? aVal - bVal
          : String(aVal).localeCompare(String(bVal));

      return sortDirection === "asc" ? comparison : -comparison;
    });
    return copy;
  }, [rows, sortColumn, sortDirection]);

  const pageCount = Math.max(1, Math.ceil(sortedRows.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount - 1);
  const pageRows = sortedRows.slice(currentPage * PAGE_SIZE, currentPage * PAGE_SIZE + PAGE_SIZE);

  function toggleSort(column: string) {
    if (sortColumn !== column) {
      setSortColumn(column);
      setSortDirection("asc");
      return;
    }
    setSortDirection((prev) => (prev === "asc" ? "desc" : "asc"));
    setPage(0);
  }

  return (
    <div className="overflow-hidden rounded-xl border border-surface-border bg-surface-raised">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-surface-border px-4 py-2.5">
        <span className="text-xs font-medium text-gray-400">
          {rows.length.toLocaleString()} row{rows.length === 1 ? "" : "s"} returned
        </span>
        <div className="flex flex-wrap items-center gap-2">
          <Badge icon={<Clock className="h-3 w-3" aria-hidden="true" />} label={formatLatency(executionTimeMs)} />
          <Badge icon={<Database className="h-3 w-3" aria-hidden="true" />} label={formatBytes(estimatedBytes)} />
          {cacheHit && (
            <Badge
              icon={<Zap className="h-3 w-3" aria-hidden="true" />}
              label="Cache hit"
              tone="success"
            />
          )}
        </div>
      </div>

      {rows.length === 0 ? (
        <div className="px-4 py-10 text-center text-sm text-gray-500">No rows returned for this query.</div>
      ) : (
        <>
          <div className="scrollbar-thin overflow-x-auto">
            <table className="w-full min-w-max text-left text-sm">
              <thead>
                <tr className="border-b border-surface-border bg-white/[0.02]">
                  {columns.map((column) => (
                    <th key={column} className="whitespace-nowrap px-4 py-2.5 font-medium text-gray-400">
                      <button
                        type="button"
                        onClick={() => toggleSort(column)}
                        className="flex items-center gap-1.5 transition hover:text-gray-200"
                      >
                        {column}
                        <ArrowUpDown
                          className={clsx(
                            "h-3 w-3",
                            sortColumn === column ? "text-indigo-400" : "text-gray-600"
                          )}
                          aria-hidden="true"
                        />
                      </button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {pageRows.map((row, rowIndex) => (
                  <tr
                    key={rowIndex}
                    className="border-b border-surface-border/60 last:border-0 hover:bg-white/[0.02]"
                  >
                    {columns.map((column) => (
                      <td key={column} className="whitespace-nowrap px-4 py-2.5 text-gray-300">
                        {formatCellValue(row[column])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {pageCount > 1 && (
            <div className="flex items-center justify-between border-t border-surface-border px-4 py-2.5">
              <span className="text-xs text-gray-500">
                Page {currentPage + 1} of {pageCount}
              </span>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => setPage((prev) => Math.max(0, prev - 1))}
                  disabled={currentPage === 0}
                  className="rounded-md p-1.5 text-gray-400 transition hover:bg-white/5 hover:text-gray-200 disabled:cursor-not-allowed disabled:opacity-40"
                  aria-label="Previous page"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                <button
                  type="button"
                  onClick={() => setPage((prev) => Math.min(pageCount - 1, prev + 1))}
                  disabled={currentPage >= pageCount - 1}
                  className="rounded-md p-1.5 text-gray-400 transition hover:bg-white/5 hover:text-gray-200 disabled:cursor-not-allowed disabled:opacity-40"
                  aria-label="Next page"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Badge({
  icon,
  label,
  tone = "neutral",
}: {
  icon: React.ReactNode;
  label: string;
  tone?: "neutral" | "success";
}) {
  return (
    <span
      className={clsx(
        "flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium",
        tone === "success" ? "bg-emerald-500/15 text-emerald-400" : "bg-white/5 text-gray-300"
      )}
    >
      {icon}
      {label}
    </span>
  );
}
