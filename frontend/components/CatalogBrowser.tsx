"use client";

import { Database, Loader2, Search, Table2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import clsx from "clsx";
import { listTables, searchCatalog } from "@/lib/catalogApi";
import { CatalogTableSummary } from "@/lib/catalogTypes";

interface CatalogBrowserProps {
  selectedTable: string | null;
  onSelectTable: (dataset: string, table: string) => void;
}

export default function CatalogBrowser({ selectedTable, onSelectTable }: CatalogBrowserProps) {
  const [allTables, setAllTables] = useState<CatalogTableSummary[]>([]);
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<CatalogTableSummary[] | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSearching, setIsSearching] = useState(false);

  useEffect(() => {
    listTables()
      .then(setAllTables)
      .finally(() => setIsLoading(false));
  }, []);

  useEffect(() => {
    const trimmed = query.trim();
    if (!trimmed) {
      setSearchResults(null);
      return;
    }
    setIsSearching(true);
    const handle = window.setTimeout(() => {
      searchCatalog(trimmed)
        .then(setSearchResults)
        .finally(() => setIsSearching(false));
    }, 300);
    return () => window.clearTimeout(handle);
  }, [query]);

  const visibleTables = useMemo(() => searchResults ?? allTables, [searchResults, allTables]);

  return (
    <div className="flex h-full flex-col rounded-xl border border-surface-border bg-surface-raised">
      <div className="border-b border-surface-border p-3">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-gray-500" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search catalog..."
            className="w-full rounded-lg border border-surface-border bg-surface py-1.5 pl-8 pr-3 text-sm text-gray-200 placeholder:text-gray-600 focus:border-indigo-500 focus:outline-none"
          />
          {isSearching && <Loader2 className="absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 animate-spin text-gray-500" />}
        </div>
      </div>

      <div className="scrollbar-thin flex-1 overflow-y-auto p-2">
        {isLoading ? (
          <div className="space-y-1.5 p-1">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="h-8 animate-pulse rounded-lg bg-white/[0.03]" />
            ))}
          </div>
        ) : visibleTables.length === 0 ? (
          <p className="px-2 py-6 text-center text-xs text-gray-600">No tables found.</p>
        ) : (
          <ul className="space-y-0.5">
            {visibleTables.map((t) => (
              <li key={`${t.dataset}.${t.table}`}>
                <button
                  type="button"
                  onClick={() => onSelectTable(t.dataset, t.table)}
                  className={clsx(
                    "flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-sm transition",
                    selectedTable === t.table
                      ? "bg-indigo-500/15 text-indigo-400"
                      : "text-gray-300 hover:bg-white/5"
                  )}
                >
                  <Table2 className="h-3.5 w-3.5 shrink-0 text-gray-500" />
                  <span className="truncate">{t.table}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="flex items-center gap-1.5 border-t border-surface-border px-3 py-2 text-[11px] text-gray-600">
        <Database className="h-3 w-3" />
        healthcare_insurance
      </div>
    </div>
  );
}
