"use client";

import { BookOpen, Loader2, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { createGlossaryTerm, deleteGlossaryTerm, listGlossaryTerms } from "@/lib/catalogApi";
import { CatalogApiError, GlossaryTerm } from "@/lib/catalogTypes";

export default function CatalogGlossary() {
  const [terms, setTerms] = useState<GlossaryTerm[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [termId, setTermId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [description, setDescription] = useState("");
  const [isCreating, setIsCreating] = useState(false);

  function refresh() {
    setIsLoading(true);
    listGlossaryTerms()
      .then(setTerms)
      .catch((err) => setError(err instanceof CatalogApiError ? err.message : "Failed to load glossary."))
      .finally(() => setIsLoading(false));
  }

  useEffect(refresh, []);

  async function handleCreate() {
    if (!termId.trim() || !displayName.trim()) return;
    setIsCreating(true);
    setError(null);
    try {
      await createGlossaryTerm(termId.trim(), displayName.trim(), description.trim());
      setTermId("");
      setDisplayName("");
      setDescription("");
      refresh();
    } catch (err) {
      setError(err instanceof CatalogApiError ? err.message : "Failed to create term.");
    } finally {
      setIsCreating(false);
    }
  }

  async function handleDelete(id: string) {
    try {
      await deleteGlossaryTerm(id);
      setTerms((prev) => prev.filter((t) => t.term_id !== id));
    } catch (err) {
      setError(err instanceof CatalogApiError ? err.message : "Failed to delete term.");
    }
  }

  return (
    <div className="rounded-xl border border-surface-border bg-surface-raised p-4">
      <div className="mb-3 flex items-center gap-2">
        <BookOpen className="h-4 w-4 text-gray-400" />
        <h3 className="text-sm font-medium text-gray-200">Business Glossary</h3>
      </div>

      <div className="mb-3 grid grid-cols-[1fr_1fr_1.5fr_auto] gap-2">
        <input
          value={termId}
          onChange={(e) => setTermId(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "-"))}
          placeholder="term-id"
          className="rounded-md border border-surface-border bg-surface px-2 py-1.5 text-xs text-gray-200 placeholder:text-gray-600 focus:border-indigo-500 focus:outline-none"
        />
        <input
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          placeholder="Display name"
          className="rounded-md border border-surface-border bg-surface px-2 py-1.5 text-xs text-gray-200 placeholder:text-gray-600 focus:border-indigo-500 focus:outline-none"
        />
        <input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Description"
          className="rounded-md border border-surface-border bg-surface px-2 py-1.5 text-xs text-gray-200 placeholder:text-gray-600 focus:border-indigo-500 focus:outline-none"
        />
        <button
          type="button"
          onClick={handleCreate}
          disabled={isCreating || !termId.trim() || !displayName.trim()}
          className="flex items-center gap-1 rounded-md bg-indigo-600 px-2.5 py-1.5 text-xs font-medium text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {isCreating ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plus className="h-3 w-3" />}
        </button>
      </div>

      {error && <p className="mb-2 text-xs text-red-400">{error}</p>}

      {isLoading ? (
        <div className="h-16 animate-pulse rounded-lg bg-white/[0.03]" />
      ) : terms.length === 0 ? (
        <p className="text-xs text-gray-600">No glossary terms defined yet.</p>
      ) : (
        <ul className="space-y-1.5">
          {terms.map((term) => (
            <li key={term.term_id} className="flex items-start justify-between gap-3 rounded-lg bg-white/[0.03] px-3 py-2">
              <div>
                <div className="text-sm font-medium text-gray-200">{term.display_name}</div>
                {term.description && <div className="text-xs text-gray-500">{term.description}</div>}
              </div>
              <button
                type="button"
                onClick={() => handleDelete(term.term_id)}
                className="shrink-0 rounded-md p-1 text-gray-500 hover:bg-white/5 hover:text-red-400"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
