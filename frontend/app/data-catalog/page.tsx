"use client";

import { Library } from "lucide-react";
import { useEffect, useState } from "react";
import CatalogBrowser from "@/components/CatalogBrowser";
import CatalogGlossary from "@/components/CatalogGlossary";
import CatalogLineage from "@/components/CatalogLineage";
import CatalogPendingApprovals from "@/components/CatalogPendingApprovals";
import CatalogTableDetail from "@/components/CatalogTableDetail";

const CHANGED_BY_STORAGE_KEY = "catalog_changed_by";

export default function DataCatalogPage() {
  const [selected, setSelected] = useState<{ dataset: string; table: string } | null>(null);
  const [changedBy, setChangedBy] = useState("");

  useEffect(() => {
    const saved = window.localStorage.getItem(CHANGED_BY_STORAGE_KEY);
    if (saved) setChangedBy(saved);
  }, []);

  function handleChangedByChange(value: string) {
    setChangedBy(value);
    window.localStorage.setItem(CHANGED_BY_STORAGE_KEY, value);
  }

  return (
    <main className="mx-auto max-w-6xl px-6 py-10">
      <header className="mb-8 flex items-center gap-3">
        <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-emerald-500/15">
          <Library className="h-5 w-5 text-emerald-400" aria-hidden="true" />
        </div>
        <div>
          <h1 className="text-xl font-semibold text-gray-100">Data Governance Catalog</h1>
          <p className="text-sm text-gray-500">
            Powered by Google Cloud Dataplex Catalog — schema, business glossary, PII detection, and lineage.
          </p>
        </div>
      </header>

      <div className="mb-6">
        <CatalogPendingApprovals reviewerName={changedBy} onReviewerNameChange={handleChangedByChange} />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[260px_1fr]">
        <div className="lg:h-[560px]">
          <CatalogBrowser selectedTable={selected?.table ?? null} onSelectTable={(dataset, table) => setSelected({ dataset, table })} />
        </div>

        <div className="space-y-6">
          {selected ? (
            <CatalogTableDetail
              dataset={selected.dataset}
              table={selected.table}
              changedBy={changedBy}
              onChangedByChange={handleChangedByChange}
            />
          ) : (
            <div className="flex h-64 items-center justify-center rounded-xl border border-surface-border bg-surface-raised text-sm text-gray-500">
              Select a table from the catalog to view its schema and governance metadata.
            </div>
          )}

          <CatalogGlossary />
          <CatalogLineage />
        </div>
      </div>
    </main>
  );
}
