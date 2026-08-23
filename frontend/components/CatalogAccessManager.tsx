"use client";

import { Loader2, Lock, Plus, ShieldCheck, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { getColumnAccess, grantColumnReader, revokeColumnReader } from "@/lib/catalogApi";
import { AccessRestrictionResponse, CatalogApiError } from "@/lib/catalogTypes";

interface CatalogAccessManagerProps {
  dataset: string;
  table: string;
  column: string;
  onClose: () => void;
}

type PrincipalType = "user" | "group" | "serviceAccount";

const PRINCIPAL_TYPE_LABELS: Record<PrincipalType, string> = {
  user: "User",
  group: "Group",
  serviceAccount: "Service account",
};

function readerLabel(principal: string): { type: string; value: string } {
  const [type = "", ...rest] = principal.split(":");
  return { type, value: rest.join(":") };
}

export default function CatalogAccessManager({ dataset, table, column, onClose }: CatalogAccessManagerProps) {
  const [access, setAccess] = useState<AccessRestrictionResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [principalType, setPrincipalType] = useState<PrincipalType>("user");
  const [principalValue, setPrincipalValue] = useState("");
  const [isGranting, setIsGranting] = useState(false);
  const [revokingPrincipal, setRevokingPrincipal] = useState<string | null>(null);

  const load = useCallback(() => {
    setIsLoading(true);
    getColumnAccess(dataset, table, column)
      .then(setAccess)
      .catch((err) => setError(err instanceof CatalogApiError ? err.message : "Failed to load access info."))
      .finally(() => setIsLoading(false));
  }, [dataset, table, column]);

  useEffect(load, [load]);

  async function handleGrant() {
    if (!principalValue.trim()) return;
    setIsGranting(true);
    setError(null);
    try {
      const updated = await grantColumnReader(dataset, table, column, `${principalType}:${principalValue.trim()}`);
      setAccess(updated);
      setPrincipalValue("");
    } catch (err) {
      setError(err instanceof CatalogApiError ? err.message : "Failed to grant access.");
    } finally {
      setIsGranting(false);
    }
  }

  async function handleRevoke(principal: string) {
    setRevokingPrincipal(principal);
    setError(null);
    try {
      const updated = await revokeColumnReader(dataset, table, column, principal);
      setAccess(updated);
    } catch (err) {
      setError(err instanceof CatalogApiError ? err.message : "Failed to revoke access.");
    } finally {
      setRevokingPrincipal(null);
    }
  }

  const isAppServiceAccount = (principal: string) => principal.includes("serviceAccount:") && principal.includes("data-governance-backend@");

  return (
    <div className="mt-3 space-y-3 rounded-lg border border-red-500/20 bg-surface p-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-xs font-medium text-gray-300">
          <Lock className="h-3.5 w-3.5 text-red-400" />
          Manage access: {column}
        </div>
        <button type="button" onClick={onClose} className="rounded-md p-1 text-gray-500 hover:bg-white/5 hover:text-gray-300">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      {isLoading ? (
        <div className="h-12 animate-pulse rounded-lg bg-white/[0.03]" />
      ) : !access?.level ? (
        <p className="text-xs text-gray-600">This column isn't currently restricted.</p>
      ) : (
        <>
          <p className="text-[11px] text-gray-500">
            Only the principals below can read this column's values — everyone else, including project Owners, is blocked by BigQuery itself.
          </p>

          <ul className="space-y-1">
            {access.readers.map((principal) => {
              const { type, value } = readerLabel(principal);
              const isSelf = isAppServiceAccount(principal);
              return (
                <li key={principal} className="flex items-center justify-between gap-2 rounded-md bg-white/[0.03] px-2.5 py-1.5 text-xs">
                  <div className="flex items-center gap-2 truncate">
                    <ShieldCheck className="h-3 w-3 shrink-0 text-emerald-400" />
                    <span className="truncate text-gray-200">{value}</span>
                    <span className="shrink-0 rounded bg-white/5 px-1.5 py-0.5 text-[10px] text-gray-500">{type}</span>
                    {isSelf && <span className="shrink-0 text-[10px] text-gray-600">(this app)</span>}
                  </div>
                  {!isSelf && (
                    <button
                      type="button"
                      onClick={() => handleRevoke(principal)}
                      disabled={revokingPrincipal === principal}
                      className="shrink-0 rounded-md p-1 text-gray-500 hover:bg-white/5 hover:text-red-400 disabled:opacity-50"
                      title="Revoke access"
                    >
                      {revokingPrincipal === principal ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />}
                    </button>
                  )}
                </li>
              );
            })}
          </ul>

          <div className="flex items-center gap-1.5">
            <select
              value={principalType}
              onChange={(e) => setPrincipalType(e.target.value as PrincipalType)}
              className="rounded-md border border-surface-border bg-surface-raised px-2 py-1.5 text-xs text-gray-200 focus:border-indigo-500 focus:outline-none"
            >
              {(Object.keys(PRINCIPAL_TYPE_LABELS) as PrincipalType[]).map((t) => (
                <option key={t} value={t}>
                  {PRINCIPAL_TYPE_LABELS[t]}
                </option>
              ))}
            </select>
            <input
              type="text"
              value={principalValue}
              onChange={(e) => setPrincipalValue(e.target.value)}
              placeholder="email address"
              className="flex-1 rounded-md border border-surface-border bg-surface-raised px-2 py-1.5 text-xs text-gray-200 placeholder:text-gray-600 focus:border-indigo-500 focus:outline-none"
            />
            <button
              type="button"
              onClick={handleGrant}
              disabled={isGranting || !principalValue.trim()}
              className="flex items-center gap-1 rounded-md bg-indigo-600 px-2.5 py-1.5 text-xs font-medium text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isGranting ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plus className="h-3 w-3" />}
              Grant
            </button>
          </div>
        </>
      )}

      {error && <p className="text-xs text-red-400">{error}</p>}
    </div>
  );
}
