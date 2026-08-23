"use client";

import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCopy,
  ListChecks,
  Loader2,
  Plus,
  ShieldQuestion,
  Trash2,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import clsx from "clsx";
import { addQualityRule, deleteQualityRule, getQualityResult, listQualityRules, triggerQualityScan } from "@/lib/catalogApi";
import {
  CatalogApiError,
  CatalogColumnSchema,
  QualityDimension,
  QualityRule,
  QualityRuleRequest,
  QualityRuleType,
  QualityScanResponse,
} from "@/lib/catalogTypes";

interface CatalogQualityRulesProps {
  dataset: string;
  table: string;
  columns: CatalogColumnSchema[];
}

const RULE_TYPE_LABELS: Record<QualityRuleType, string> = {
  non_null: "Not null",
  unique: "Unique",
  range: "Value in range",
  regex: "Matches pattern",
  set: "Value in set",
};

const DEFAULT_DIMENSION_FOR_TYPE: Record<QualityRuleType, QualityDimension> = {
  non_null: "COMPLETENESS",
  unique: "UNIQUENESS",
  range: "VALIDITY",
  regex: "VALIDITY",
  set: "VALIDITY",
};

const DIMENSIONS: QualityDimension[] = ["COMPLETENESS", "UNIQUENESS", "VALIDITY", "ACCURACY", "CONSISTENCY", "TIMELINESS"];

const EMPTY_FORM: QualityRuleRequest = {
  column: "",
  dimension: "COMPLETENESS",
  rule_type: "non_null",
  threshold: 1.0,
  min_value: "",
  max_value: "",
  regex: "",
  set_values: [],
};

function ruleSummary(rule: QualityRule): string {
  switch (rule.rule_type) {
    case "range":
      return `between ${rule.min_value} and ${rule.max_value}`;
    case "regex":
      return `matches /${rule.regex}/`;
    case "set":
      return `in {${(rule.set_values ?? []).join(", ")}}`;
    default:
      return "";
  }
}

export default function CatalogQualityRules({ dataset, table, columns }: CatalogQualityRulesProps) {
  const [rules, setRules] = useState<QualityRule[]>([]);
  const [isLoadingRules, setIsLoadingRules] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [isFormOpen, setIsFormOpen] = useState(false);
  const [form, setForm] = useState<QualityRuleRequest>(EMPTY_FORM);
  const [setValuesInput, setSetValuesInput] = useState("");
  const [isAdding, setIsAdding] = useState(false);

  const [scanResult, setScanResult] = useState<QualityScanResponse | null>(null);
  const [isScanning, setIsScanning] = useState(false);
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);

  const loadRules = useCallback(() => {
    setIsLoadingRules(true);
    listQualityRules(dataset, table)
      .then((res) => setRules(res.rules))
      .catch((err) => setError(err instanceof CatalogApiError ? err.message : "Failed to load quality rules."))
      .finally(() => setIsLoadingRules(false));
  }, [dataset, table]);

  useEffect(() => {
    loadRules();
    setScanResult(null);
    setIsFormOpen(false);
  }, [loadRules]);

  function handleRuleTypeChange(ruleType: QualityRuleType) {
    setForm((prev) => ({ ...prev, rule_type: ruleType, dimension: DEFAULT_DIMENSION_FOR_TYPE[ruleType] }));
  }

  async function handleAddRule() {
    setIsAdding(true);
    setError(null);
    try {
      const payload: QualityRuleRequest = {
        ...form,
        min_value: form.rule_type === "range" ? form.min_value : null,
        max_value: form.rule_type === "range" ? form.max_value : null,
        regex: form.rule_type === "regex" ? form.regex : null,
        set_values:
          form.rule_type === "set"
            ? setValuesInput.split(",").map((v) => v.trim()).filter(Boolean)
            : null,
      };
      const res = await addQualityRule(dataset, table, payload);
      setRules(res.rules);
      setForm(EMPTY_FORM);
      setSetValuesInput("");
      setIsFormOpen(false);
    } catch (err) {
      setError(err instanceof CatalogApiError ? err.message : "Failed to add rule.");
    } finally {
      setIsAdding(false);
    }
  }

  async function handleDeleteRule(index: number) {
    try {
      const res = await deleteQualityRule(dataset, table, index);
      setRules(res.rules);
    } catch (err) {
      setError(err instanceof CatalogApiError ? err.message : "Failed to delete rule.");
    }
  }

  async function handleRunScan() {
    setIsScanning(true);
    setError(null);
    try {
      await triggerQualityScan(dataset, table);
      // Data quality scans generate + run one query per rule and routinely take 30-90s+,
      // noticeably longer than a plain profile scan — poll generously.
      for (let attempt = 0; attempt < 40; attempt++) {
        await new Promise((r) => window.setTimeout(r, 4000));
        const result = await getQualityResult(dataset, table);
        if (result.state === "SUCCEEDED" || result.state === "FAILED") {
          setScanResult(result);
          break;
        }
      }
    } catch (err) {
      setError(err instanceof CatalogApiError ? err.message : "Quality scan failed.");
    } finally {
      setIsScanning(false);
    }
  }

  function copyQuery(query: string, index: number) {
    navigator.clipboard.writeText(query).then(() => {
      setCopiedIndex(index);
      window.setTimeout(() => setCopiedIndex(null), 1500);
    });
  }

  return (
    <div className="rounded-xl border border-surface-border bg-surface-raised p-4">
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ListChecks className="h-4 w-4 text-gray-400" />
          <h3 className="text-sm font-medium text-gray-300">Data quality rules</h3>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setIsFormOpen((v) => !v)}
            className="flex items-center gap-1.5 rounded-md bg-white/5 px-2.5 py-1.5 text-xs font-medium text-gray-300 hover:bg-white/10"
          >
            <Plus className="h-3 w-3" /> Add rule
          </button>
          <button
            type="button"
            onClick={handleRunScan}
            disabled={isScanning || rules.length === 0}
            title={rules.length === 0 ? "Add at least one rule first" : undefined}
            className="flex items-center gap-1.5 rounded-md bg-indigo-600 px-2.5 py-1.5 text-xs font-medium text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isScanning ? <Loader2 className="h-3 w-3 animate-spin" /> : <ShieldQuestion className="h-3 w-3" />}
            Run quality scan
          </button>
        </div>
      </div>

      {isFormOpen && (
        <div className="mb-3 space-y-2 rounded-lg border border-surface-border bg-surface p-3">
          <div className="grid grid-cols-3 gap-2">
            <label className="text-xs text-gray-500">
              Column
              <select
                value={form.column}
                onChange={(e) => setForm({ ...form, column: e.target.value })}
                className="mt-1 w-full rounded-md border border-surface-border bg-surface-raised px-2 py-1.5 text-sm text-gray-200 focus:border-indigo-500 focus:outline-none"
              >
                <option value="">Select column</option>
                {columns.map((c) => (
                  <option key={c.name} value={c.name}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs text-gray-500">
              Rule
              <select
                value={form.rule_type}
                onChange={(e) => handleRuleTypeChange(e.target.value as QualityRuleType)}
                className="mt-1 w-full rounded-md border border-surface-border bg-surface-raised px-2 py-1.5 text-sm text-gray-200 focus:border-indigo-500 focus:outline-none"
              >
                {(Object.keys(RULE_TYPE_LABELS) as QualityRuleType[]).map((rt) => (
                  <option key={rt} value={rt}>
                    {RULE_TYPE_LABELS[rt]}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs text-gray-500">
              Dimension
              <select
                value={form.dimension}
                onChange={(e) => setForm({ ...form, dimension: e.target.value as QualityDimension })}
                className="mt-1 w-full rounded-md border border-surface-border bg-surface-raised px-2 py-1.5 text-sm text-gray-200 focus:border-indigo-500 focus:outline-none"
              >
                {DIMENSIONS.map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {form.rule_type === "range" && (
            <div className="grid grid-cols-2 gap-2">
              <label className="text-xs text-gray-500">
                Min value
                <input
                  value={form.min_value ?? ""}
                  onChange={(e) => setForm({ ...form, min_value: e.target.value })}
                  className="mt-1 w-full rounded-md border border-surface-border bg-surface-raised px-2 py-1.5 text-sm text-gray-200 focus:border-indigo-500 focus:outline-none"
                />
              </label>
              <label className="text-xs text-gray-500">
                Max value
                <input
                  value={form.max_value ?? ""}
                  onChange={(e) => setForm({ ...form, max_value: e.target.value })}
                  className="mt-1 w-full rounded-md border border-surface-border bg-surface-raised px-2 py-1.5 text-sm text-gray-200 focus:border-indigo-500 focus:outline-none"
                />
              </label>
            </div>
          )}
          {form.rule_type === "regex" && (
            <label className="block text-xs text-gray-500">
              Regex pattern
              <input
                value={form.regex ?? ""}
                onChange={(e) => setForm({ ...form, regex: e.target.value })}
                placeholder="^MEM-[0-9]{6}$"
                className="mt-1 w-full rounded-md border border-surface-border bg-surface-raised px-2 py-1.5 text-sm text-gray-200 placeholder:text-gray-600 focus:border-indigo-500 focus:outline-none"
              />
            </label>
          )}
          {form.rule_type === "set" && (
            <label className="block text-xs text-gray-500">
              Allowed values (comma-separated)
              <input
                value={setValuesInput}
                onChange={(e) => setSetValuesInput(e.target.value)}
                placeholder="Paid, Denied, Pending"
                className="mt-1 w-full rounded-md border border-surface-border bg-surface-raised px-2 py-1.5 text-sm text-gray-200 placeholder:text-gray-600 focus:border-indigo-500 focus:outline-none"
              />
            </label>
          )}

          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={() => setIsFormOpen(false)}
              className="rounded-md px-2.5 py-1.5 text-xs text-gray-400 hover:bg-white/5"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleAddRule}
              disabled={isAdding || !form.column}
              className="flex items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isAdding && <Loader2 className="h-3 w-3 animate-spin" />}
              Save rule
            </button>
          </div>
        </div>
      )}

      {error && (
        <div className="mb-3 flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          {error}
        </div>
      )}

      {isLoadingRules ? (
        <div className="h-16 animate-pulse rounded-lg bg-white/[0.03]" />
      ) : rules.length === 0 ? (
        <p className="text-xs text-gray-600">No rules defined yet — add one to enable quality scanning.</p>
      ) : (
        <ul className="space-y-1.5">
          {rules.map((rule) => {
            const ruleResult = scanResult?.rules.find(
              (r) => r.column === rule.column && r.dimension === rule.dimension
            );
            return (
              <li key={rule.index} className="rounded-lg bg-white/[0.03] px-3 py-2 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    {ruleResult && (
                      ruleResult.passed ? (
                        <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-400" />
                      ) : (
                        <XCircle className="h-3.5 w-3.5 shrink-0 text-red-400" />
                      )
                    )}
                    <span className="font-mono text-gray-200">{rule.column}</span>
                    <span className="text-gray-500">{RULE_TYPE_LABELS[rule.rule_type]}</span>
                    <span className="text-gray-600">{ruleSummary(rule)}</span>
                    <span className="rounded bg-white/5 px-1.5 py-0.5 text-[10px] text-gray-500">{rule.dimension}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    {ruleResult && (
                      <span className={clsx("font-medium", ruleResult.passed ? "text-emerald-400" : "text-red-400")}>
                        {(ruleResult.pass_ratio * 100).toFixed(1)}%
                      </span>
                    )}
                    <button
                      type="button"
                      onClick={() => handleDeleteRule(rule.index)}
                      className="rounded-md p-1 text-gray-500 hover:bg-white/5 hover:text-red-400"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
                {ruleResult && !ruleResult.passed && ruleResult.failing_rows_query && (
                  <div className="mt-2 flex items-start gap-2 rounded-md border border-red-500/20 bg-red-500/5 p-2">
                    <code className="flex-1 overflow-x-auto whitespace-pre-wrap break-all font-mono text-[10.5px] text-red-300">
                      {ruleResult.failing_rows_query}
                    </code>
                    <button
                      type="button"
                      onClick={() => copyQuery(ruleResult.failing_rows_query!, rule.index)}
                      className="shrink-0 rounded-md p-1 text-gray-500 hover:bg-white/5 hover:text-gray-300"
                      title="Copy failing-rows query"
                    >
                      {copiedIndex === rule.index ? (
                        <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
                      ) : (
                        <ClipboardCopy className="h-3.5 w-3.5" />
                      )}
                    </button>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {scanResult && scanResult.state === "SUCCEEDED" && (
        <div className="mt-3 flex items-center gap-3 border-t border-surface-border pt-3 text-xs">
          <span className={clsx("font-semibold", scanResult.passed ? "text-emerald-400" : "text-red-400")}>
            Overall: {scanResult.score?.toFixed(1)}% {scanResult.passed ? "passed" : "failed"}
          </span>
          <span className="text-gray-500">{scanResult.row_count?.toLocaleString()} rows evaluated</span>
        </div>
      )}
    </div>
  );
}
