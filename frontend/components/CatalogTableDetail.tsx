"use client";

import {
  AlertTriangle,
  BookMarked,
  Clock,
  Loader2,
  Lock,
  Pencil,
  ScanSearch,
  Sparkles,
  Tag,
  Trash2,
  X,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import clsx from "clsx";
import CatalogAccessManager from "@/components/CatalogAccessManager";
import CatalogAuditHistory from "@/components/CatalogAuditHistory";
import CatalogQualityRules from "@/components/CatalogQualityRules";
import {
  deleteTag,
  getProfileResult,
  getTableDetail,
  linkGlossaryTerm,
  listGlossaryTerms,
  scanTableForPii,
  triggerProfileScan,
  unlinkGlossaryTerm,
  upsertTag,
} from "@/lib/catalogApi";
import {
  CatalogApiError,
  CatalogTableDetail as CatalogTableDetailType,
  DataProfileResponse,
  GlossaryTerm,
  GovernanceTag,
  PiiLevel,
  PiiScanResponse,
} from "@/lib/catalogTypes";

interface CatalogTableDetailProps {
  dataset: string;
  table: string;
  changedBy: string;
  onChangedByChange: (value: string) => void;
}

const PII_BADGE_CLASS: Record<PiiLevel, string> = {
  NONE: "bg-white/5 text-gray-500",
  LOW: "bg-amber-500/15 text-amber-400",
  HIGH: "bg-red-500/15 text-red-400",
};

const EMPTY_TAG_FORM: GovernanceTag = { data_owner: "", pii_level: "NONE", retention_days: 0, notes: "" };

export default function CatalogTableDetail({ dataset, table, changedBy, onChangedByChange }: CatalogTableDetailProps) {
  const [detail, setDetail] = useState<CatalogTableDetailType | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pendingNotice, setPendingNotice] = useState<string | null>(null);

  const [editingTarget, setEditingTarget] = useState<string | null | undefined>(undefined);
  const [tagForm, setTagForm] = useState<GovernanceTag>(EMPTY_TAG_FORM);
  const [isSavingTag, setIsSavingTag] = useState(false);

  const [piiScan, setPiiScan] = useState<PiiScanResponse | null>(null);
  const [isPiiScanning, setIsPiiScanning] = useState(false);

  const [profile, setProfile] = useState<DataProfileResponse | null>(null);
  const [isProfiling, setIsProfiling] = useState(false);

  const [glossaryTerms, setGlossaryTerms] = useState<GlossaryTerm[]>([]);
  const [linkingColumn, setLinkingColumn] = useState<string | null | undefined>(undefined);
  const [selectedTermId, setSelectedTermId] = useState("");
  const [isLinkingTerm, setIsLinkingTerm] = useState(false);

  const [managingAccessColumn, setManagingAccessColumn] = useState<string | null>(null);

  useEffect(() => {
    listGlossaryTerms().then(setGlossaryTerms).catch(() => setGlossaryTerms([]));
  }, []);

  const load = useCallback(() => {
    setIsLoading(true);
    setError(null);
    getTableDetail(dataset, table)
      .then(setDetail)
      .catch((err) => setError(err instanceof CatalogApiError ? err.message : "Failed to load table."))
      .finally(() => setIsLoading(false));
  }, [dataset, table]);

  useEffect(() => {
    load();
    setPiiScan(null);
    setProfile(null);
    setEditingTarget(undefined);
    setLinkingColumn(undefined);
    setManagingAccessColumn(null);
    setPendingNotice(null);
  }, [load]);

  function openEditor(target: string | null) {
    const existing = target === null ? detail?.table_tag : detail?.column_tags[target];
    setTagForm(existing ?? EMPTY_TAG_FORM);
    setEditingTarget(target);
  }

  function touchesHighPii(oldLevel: PiiLevel | undefined, newLevel: PiiLevel | null): boolean {
    return oldLevel === "HIGH" || newLevel === "HIGH";
  }

  async function handleSaveTag() {
    if (editingTarget && touchesHighPii(detail?.column_tags[editingTarget]?.pii_level, tagForm.pii_level) && !changedBy.trim()) {
      setError('Enter your name in "Editing as" (top-right) before setting or removing a HIGH-PII restriction — approvals need to know who proposed it.');
      return;
    }
    setIsSavingTag(true);
    setPendingNotice(null);
    setError(null);
    try {
      const result = await upsertTag(dataset, table, { column: editingTarget, ...tagForm, changed_by: changedBy });
      if (result.status === "PENDING_APPROVAL") {
        setPendingNotice(result.message);
      } else if (result.detail) {
        setDetail(result.detail);
      }
      setEditingTarget(undefined);
    } catch (err) {
      setError(err instanceof CatalogApiError ? err.message : "Failed to save tag.");
    } finally {
      setIsSavingTag(false);
    }
  }

  async function handleDeleteTag(target: string | null) {
    if (target && touchesHighPii(detail?.column_tags[target]?.pii_level, null) && !changedBy.trim()) {
      setError('Enter your name in "Editing as" (top-right) before removing a HIGH-PII restriction — approvals need to know who proposed it.');
      return;
    }
    setPendingNotice(null);
    setError(null);
    try {
      const result = await deleteTag(dataset, table, target, changedBy);
      if (result.status === "PENDING_APPROVAL") {
        setPendingNotice(result.message);
      } else if (result.detail) {
        setDetail(result.detail);
      }
    } catch (err) {
      setError(err instanceof CatalogApiError ? err.message : "Failed to remove tag.");
    }
  }

  function openLinkPicker(column: string) {
    setSelectedTermId(detail?.column_glossary_links[column]?.term_id ?? "");
    setLinkingColumn(column);
  }

  async function handleLinkTerm() {
    const term = glossaryTerms.find((t) => t.term_id === selectedTermId);
    if (!term || linkingColumn === undefined) return;
    setIsLinkingTerm(true);
    try {
      const updated = await linkGlossaryTerm(dataset, table, {
        column: linkingColumn,
        term_id: term.term_id,
        term_display_name: term.display_name,
      });
      setDetail(updated);
      setLinkingColumn(undefined);
    } catch (err) {
      setError(err instanceof CatalogApiError ? err.message : "Failed to link term.");
    } finally {
      setIsLinkingTerm(false);
    }
  }

  async function handleUnlinkTerm(column: string) {
    try {
      const updated = await unlinkGlossaryTerm(dataset, table, column);
      setDetail(updated);
    } catch (err) {
      setError(err instanceof CatalogApiError ? err.message : "Failed to unlink term.");
    }
  }

  async function handlePiiScan() {
    setIsPiiScanning(true);
    try {
      setPiiScan(await scanTableForPii(dataset, table));
    } catch (err) {
      setError(err instanceof CatalogApiError ? err.message : "PII scan failed.");
    } finally {
      setIsPiiScanning(false);
    }
  }

  async function handleProfileScan() {
    setIsProfiling(true);
    try {
      await triggerProfileScan(dataset, table);
      for (let attempt = 0; attempt < 15; attempt++) {
        await new Promise((r) => window.setTimeout(r, 3000));
        const result = await getProfileResult(dataset, table);
        if (result.state === "SUCCEEDED" || result.state === "FAILED") {
          setProfile(result);
          break;
        }
      }
    } catch (err) {
      setError(err instanceof CatalogApiError ? err.message : "Data quality scan failed.");
    } finally {
      setIsProfiling(false);
    }
  }

  if (isLoading) {
    return <div className="h-64 animate-pulse rounded-xl border border-surface-border bg-surface-raised" />;
  }
  if (error && !detail) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
        <AlertTriangle className="h-4 w-4 shrink-0" />
        {error}
      </div>
    );
  }
  if (!detail) return null;

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-surface-border bg-surface-raised p-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-base font-semibold text-gray-100">{detail.display_name}</h2>
            <p className="mt-0.5 font-mono text-xs text-gray-500">{detail.fully_qualified_name}</p>
          </div>
          <label className="shrink-0 text-right text-[11px] text-gray-500">
            Editing as
            <input
              type="text"
              value={changedBy}
              onChange={(e) => onChangedByChange(e.target.value)}
              placeholder="your name"
              className="mt-1 block w-32 rounded-md border border-surface-border bg-surface px-2 py-1 text-xs text-gray-200 placeholder:text-gray-600 focus:border-indigo-500 focus:outline-none"
            />
          </label>
        </div>

        <div className="mt-3 flex items-center justify-between">
          <span className="text-xs font-medium uppercase tracking-wide text-gray-500">Table governance tag</span>
          <button
            type="button"
            onClick={() => openEditor(null)}
            className="flex items-center gap-1 rounded-md bg-white/5 px-2 py-1 text-xs text-gray-300 hover:bg-white/10"
          >
            <Pencil className="h-3 w-3" /> {detail.table_tag ? "Edit" : "Add tag"}
          </button>
        </div>
        {detail.table_tag ? (
          <TagSummary tag={detail.table_tag} onDelete={() => handleDeleteTag(null)} />
        ) : (
          <p className="mt-1 text-xs text-gray-600">No governance tag set.</p>
        )}
        {editingTarget === null && (
          <TagEditor form={tagForm} onChange={setTagForm} onCancel={() => setEditingTarget(undefined)} onSave={handleSaveTag} isSaving={isSavingTag} />
        )}
      </div>

      {pendingNotice && (
        <div className="flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
          <Clock className="h-3.5 w-3.5 shrink-0" />
          {pendingNotice}
        </div>
      )}

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          {error}
        </div>
      )}

      <div className="rounded-xl border border-surface-border bg-surface-raised p-4">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-sm font-medium text-gray-300">Schema &amp; column tags</h3>
          <button
            type="button"
            onClick={handlePiiScan}
            disabled={isPiiScanning}
            className="flex items-center gap-1.5 rounded-md bg-indigo-600 px-2.5 py-1.5 text-xs font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
          >
            {isPiiScanning ? <Loader2 className="h-3 w-3 animate-spin" /> : <ScanSearch className="h-3 w-3" />}
            Scan for PII
          </button>
        </div>

        <div className="scrollbar-thin overflow-x-auto">
          <table className="w-full min-w-max text-left text-sm">
            <thead>
              <tr className="text-xs text-gray-500">
                <th className="py-1.5 pr-4 font-medium">Column</th>
                <th className="py-1.5 pr-4 font-medium">Type</th>
                <th className="py-1.5 pr-4 font-medium">PII (DLP)</th>
                <th className="py-1.5 pr-4 font-medium">Governance Tag</th>
                <th className="py-1.5 pr-4 font-medium">Glossary Term</th>
                <th className="py-1.5 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {detail.columns.map((col) => {
                const piiFinding = piiScan?.columns.find((c) => c.column === col.name);
                const tag = detail.column_tags[col.name];
                const link = detail.column_glossary_links[col.name];
                return (
                  <tr key={col.name} className="border-t border-surface-border/60">
                    <td className="whitespace-nowrap py-2 pr-4 font-mono text-xs text-gray-200">{col.name}</td>
                    <td className="whitespace-nowrap py-2 pr-4 text-xs text-gray-500">{col.data_type}</td>
                    <td className="whitespace-nowrap py-2 pr-4">
                      {piiFinding ? (
                        <span
                          title={Object.entries(piiFinding.info_type_counts).map(([k, v]) => `${k}: ${v}`).join(", ")}
                          className={clsx("rounded-full px-2 py-0.5 text-[11px] font-medium", PII_BADGE_CLASS[piiFinding.recommended_pii_level])}
                        >
                          {piiFinding.recommended_pii_level === "NONE" ? "clear" : piiFinding.recommended_pii_level}
                        </span>
                      ) : (
                        <span className="text-xs text-gray-700">—</span>
                      )}
                    </td>
                    <td className="whitespace-nowrap py-2 pr-4">
                      {tag ? (
                        <span
                          className={clsx(
                            "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium",
                            PII_BADGE_CLASS[tag.pii_level]
                          )}
                          title={tag.pii_level === "HIGH" ? "Real, BigQuery-enforced restriction is active on this column" : undefined}
                        >
                          {tag.pii_level === "HIGH" && <Lock className="h-2.5 w-2.5" />}
                          {tag.data_owner || tag.pii_level}
                        </span>
                      ) : (
                        <span className="text-xs text-gray-700">untagged</span>
                      )}
                    </td>
                    <td className="whitespace-nowrap py-2 pr-4">
                      {link ? (
                        <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[11px] font-medium text-emerald-400">
                          {link.term_display_name}
                        </span>
                      ) : (
                        <span className="text-xs text-gray-700">unlinked</span>
                      )}
                    </td>
                    <td className="whitespace-nowrap py-2">
                      <div className="flex items-center gap-1">
                        <button
                          type="button"
                          onClick={() => openEditor(col.name)}
                          className="rounded-md p-1 text-gray-500 hover:bg-white/5 hover:text-gray-300"
                          title="Edit tag"
                        >
                          <Tag className="h-3.5 w-3.5" />
                        </button>
                        {tag && (
                          <button
                            type="button"
                            onClick={() => handleDeleteTag(col.name)}
                            className="rounded-md p-1 text-gray-500 hover:bg-white/5 hover:text-red-400"
                            title="Remove tag"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => openLinkPicker(col.name)}
                          className="rounded-md p-1 text-gray-500 hover:bg-white/5 hover:text-emerald-400"
                          title="Link glossary term"
                        >
                          <BookMarked className="h-3.5 w-3.5" />
                        </button>
                        {link && (
                          <button
                            type="button"
                            onClick={() => handleUnlinkTerm(col.name)}
                            className="rounded-md p-1 text-gray-500 hover:bg-white/5 hover:text-red-400"
                            title="Unlink term"
                          >
                            <X className="h-3.5 w-3.5" />
                          </button>
                        )}
                        {tag?.pii_level === "HIGH" && (
                          <button
                            type="button"
                            onClick={() => setManagingAccessColumn(col.name)}
                            className="rounded-md p-1 text-gray-500 hover:bg-white/5 hover:text-red-400"
                            title="Manage who can read this restricted column"
                          >
                            <Lock className="h-3.5 w-3.5" />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {editingTarget !== undefined && editingTarget !== null && (
          <div className="mt-3 border-t border-surface-border pt-3">
            <p className="mb-2 text-xs font-medium text-gray-400">Editing tag for column: {editingTarget}</p>
            <TagEditor form={tagForm} onChange={setTagForm} onCancel={() => setEditingTarget(undefined)} onSave={handleSaveTag} isSaving={isSavingTag} />
          </div>
        )}

        {linkingColumn !== undefined && (
          <div className="mt-3 space-y-2 rounded-lg border border-surface-border bg-surface p-3">
            <p className="text-xs font-medium text-gray-400">Link a glossary term to: {linkingColumn}</p>
            {glossaryTerms.length === 0 ? (
              <p className="text-xs text-gray-600">No glossary terms defined yet — add one below first.</p>
            ) : (
              <select
                value={selectedTermId}
                onChange={(e) => setSelectedTermId(e.target.value)}
                className="w-full rounded-md border border-surface-border bg-surface-raised px-2 py-1.5 text-sm text-gray-200 focus:border-indigo-500 focus:outline-none"
              >
                <option value="">Select a term</option>
                {glossaryTerms.map((t) => (
                  <option key={t.term_id} value={t.term_id}>
                    {t.display_name}
                  </option>
                ))}
              </select>
            )}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setLinkingColumn(undefined)}
                className="flex items-center gap-1 rounded-md px-2.5 py-1.5 text-xs text-gray-400 hover:bg-white/5"
              >
                <X className="h-3 w-3" /> Cancel
              </button>
              <button
                type="button"
                onClick={handleLinkTerm}
                disabled={isLinkingTerm || !selectedTermId}
                className="flex items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isLinkingTerm && <Loader2 className="h-3 w-3 animate-spin" />}
                Link term
              </button>
            </div>
          </div>
        )}

        {managingAccessColumn && (
          <CatalogAccessManager
            dataset={dataset}
            table={table}
            column={managingAccessColumn}
            onClose={() => setManagingAccessColumn(null)}
          />
        )}
      </div>

      <div className="rounded-xl border border-surface-border bg-surface-raised p-4">
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-sm font-medium text-gray-300">Data quality profile</h3>
          <button
            type="button"
            onClick={handleProfileScan}
            disabled={isProfiling}
            className="flex items-center gap-1.5 rounded-md bg-white/5 px-2.5 py-1.5 text-xs font-medium text-gray-300 hover:bg-white/10 disabled:opacity-50"
          >
            {isProfiling ? <Loader2 className="h-3 w-3 animate-spin" /> : <Sparkles className="h-3 w-3" />}
            Run profile scan
          </button>
        </div>
        {!profile ? (
          <p className="text-xs text-gray-600">No profile scan run yet. This can take ~10-20 seconds.</p>
        ) : profile.state === "FAILED" ? (
          <p className="text-xs text-red-400">Profile scan failed.</p>
        ) : (
          <div className="scrollbar-thin overflow-x-auto">
            <table className="w-full min-w-max text-left text-xs">
              <thead>
                <tr className="text-gray-500">
                  <th className="py-1 pr-4 font-medium">Field</th>
                  <th className="py-1 pr-4 font-medium">Distinct Ratio</th>
                  <th className="py-1 pr-4 font-medium">Avg Length</th>
                </tr>
              </thead>
              <tbody>
                {profile.fields.map((f) => (
                  <tr key={f.name} className="border-t border-surface-border/60 text-gray-300">
                    <td className="whitespace-nowrap py-1.5 pr-4 font-mono">{f.name}</td>
                    <td className="whitespace-nowrap py-1.5 pr-4">
                      {f.profile?.distinctRatio !== undefined ? f.profile.distinctRatio.toFixed(2) : "—"}
                    </td>
                    <td className="whitespace-nowrap py-1.5 pr-4">
                      {f.profile?.stringProfile?.averageLength !== undefined
                        ? f.profile.stringProfile.averageLength.toFixed(1)
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <CatalogQualityRules dataset={dataset} table={table} columns={detail.columns} />

      <CatalogAuditHistory dataset={dataset} table={table} />
    </div>
  );
}

function TagSummary({ tag, onDelete }: { tag: GovernanceTag; onDelete: () => void }) {
  return (
    <div className="mt-1.5 flex items-center justify-between rounded-lg bg-white/[0.03] px-3 py-2 text-xs">
      <div className="space-y-0.5 text-gray-300">
        <div>
          <span className="text-gray-500">Owner:</span> {tag.data_owner || "—"} ·{" "}
          <span className={clsx("rounded px-1.5 py-0.5 font-medium", PII_BADGE_CLASS[tag.pii_level])}>{tag.pii_level}</span>{" "}
          · <span className="text-gray-500">Retention:</span> {tag.retention_days}d
        </div>
        {tag.notes && <div className="text-gray-500">{tag.notes}</div>}
      </div>
      <button type="button" onClick={onDelete} className="rounded-md p-1 text-gray-500 hover:bg-white/5 hover:text-red-400">
        <Trash2 className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

function TagEditor({
  form,
  onChange,
  onCancel,
  onSave,
  isSaving,
}: {
  form: GovernanceTag;
  onChange: (form: GovernanceTag) => void;
  onCancel: () => void;
  onSave: () => void;
  isSaving: boolean;
}) {
  return (
    <div className="mt-2 space-y-2 rounded-lg border border-surface-border bg-surface p-3">
      <div className="grid grid-cols-2 gap-2">
        <label className="text-xs text-gray-500">
          Data owner
          <input
            type="text"
            value={form.data_owner}
            onChange={(e) => onChange({ ...form, data_owner: e.target.value })}
            className="mt-1 w-full rounded-md border border-surface-border bg-surface-raised px-2 py-1.5 text-sm text-gray-200 focus:border-indigo-500 focus:outline-none"
          />
        </label>
        <label className="text-xs text-gray-500">
          PII level
          <select
            value={form.pii_level}
            onChange={(e) => onChange({ ...form, pii_level: e.target.value as PiiLevel })}
            className="mt-1 w-full rounded-md border border-surface-border bg-surface-raised px-2 py-1.5 text-sm text-gray-200 focus:border-indigo-500 focus:outline-none"
          >
            <option value="NONE">NONE</option>
            <option value="LOW">LOW</option>
            <option value="HIGH">HIGH</option>
          </select>
        </label>
        <label className="text-xs text-gray-500">
          Retention (days)
          <input
            type="number"
            min={0}
            value={form.retention_days}
            onChange={(e) => onChange({ ...form, retention_days: Number(e.target.value) })}
            className="mt-1 w-full rounded-md border border-surface-border bg-surface-raised px-2 py-1.5 text-sm text-gray-200 focus:border-indigo-500 focus:outline-none"
          />
        </label>
        <label className="col-span-2 text-xs text-gray-500">
          Notes
          <input
            type="text"
            value={form.notes}
            onChange={(e) => onChange({ ...form, notes: e.target.value })}
            className="mt-1 w-full rounded-md border border-surface-border bg-surface-raised px-2 py-1.5 text-sm text-gray-200 focus:border-indigo-500 focus:outline-none"
          />
        </label>
      </div>
      <div className="flex items-center justify-end gap-2">
        <button type="button" onClick={onCancel} className="flex items-center gap-1 rounded-md px-2.5 py-1.5 text-xs text-gray-400 hover:bg-white/5">
          <X className="h-3 w-3" /> Cancel
        </button>
        <button
          type="button"
          onClick={onSave}
          disabled={isSaving}
          className="flex items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
        >
          {isSaving && <Loader2 className="h-3 w-3 animate-spin" />}
          Save tag
        </button>
      </div>
    </div>
  );
}
