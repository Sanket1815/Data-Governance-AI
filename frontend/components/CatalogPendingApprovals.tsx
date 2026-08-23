"use client";

import { AlertTriangle, Check, Clock, Loader2, ShieldAlert, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { approveChange, listPendingApprovals, rejectChange } from "@/lib/catalogApi";
import { CatalogApiError, PendingApproval } from "@/lib/catalogTypes";

interface CatalogPendingApprovalsProps {
  reviewerName: string;
  onReviewerNameChange: (value: string) => void;
}

export default function CatalogPendingApprovals({ reviewerName, onReviewerNameChange }: CatalogPendingApprovalsProps) {
  const [approvals, setApprovals] = useState<PendingApproval[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [resolvingId, setResolvingId] = useState<string | null>(null);

  const load = useCallback(() => {
    setIsLoading(true);
    listPendingApprovals()
      .then(setApprovals)
      .catch((err) => setError(err instanceof CatalogApiError ? err.message : "Failed to load pending approvals."))
      .finally(() => setIsLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function handleResolve(approvalId: string, decision: "approve" | "reject") {
    setResolvingId(approvalId);
    setError(null);
    try {
      if (decision === "approve") {
        await approveChange(approvalId, reviewerName);
      } else {
        await rejectChange(approvalId, reviewerName);
      }
      setApprovals((prev) => prev.filter((a) => a.approval_id !== approvalId));
    } catch (err) {
      setError(err instanceof CatalogApiError ? err.message : `Failed to ${decision} change.`);
    } finally {
      setResolvingId(null);
    }
  }

  function describeChange(approval: PendingApproval): string {
    if (approval.action === "DELETE") return "remove the HIGH-PII tag and restriction";
    const level = approval.proposed_data?.pii_level;
    return level === "HIGH" ? "set a HIGH-PII restriction" : "change the PII level";
  }

  if (isLoading && approvals.length === 0) {
    return <div className="h-16 animate-pulse rounded-xl border border-surface-border bg-surface-raised" />;
  }
  if (approvals.length === 0 && !error) return null;

  return (
    <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ShieldAlert className="h-4 w-4 text-amber-400" />
          <h3 className="text-sm font-medium text-gray-200">Pending approvals</h3>
          <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[11px] font-medium text-amber-400">
            {approvals.length}
          </span>
        </div>
        <label className="text-[11px] text-gray-500">
          Reviewing as
          <input
            type="text"
            value={reviewerName}
            onChange={(e) => onReviewerNameChange(e.target.value)}
            placeholder="your name"
            className="ml-2 w-28 rounded-md border border-surface-border bg-surface px-2 py-1 text-xs text-gray-200 placeholder:text-gray-600 focus:border-indigo-500 focus:outline-none"
          />
        </label>
      </div>

      {error && (
        <div className="mb-2 flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          {error}
        </div>
      )}

      <ul className="space-y-2">
        {approvals.map((approval) => (
          <li key={approval.approval_id} className="flex items-center justify-between gap-3 rounded-lg bg-white/[0.03] px-3 py-2.5 text-xs">
            <div className="flex items-start gap-2">
              <Clock className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-400" />
              <div>
                <span className="font-medium text-gray-100">{approval.proposed_by || "unknown"}</span>{" "}
                <span className="text-gray-300">wants to {describeChange(approval)} on</span>{" "}
                <span className="font-mono text-gray-200">
                  {approval.dataset}.{approval.table_name}.{approval.column_name}
                </span>
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-1.5">
              <button
                type="button"
                onClick={() => handleResolve(approval.approval_id, "reject")}
                disabled={resolvingId === approval.approval_id}
                className="flex items-center gap-1 rounded-md bg-white/5 px-2.5 py-1.5 font-medium text-gray-300 hover:bg-white/10 disabled:opacity-50"
              >
                {resolvingId === approval.approval_id ? <Loader2 className="h-3 w-3 animate-spin" /> : <X className="h-3 w-3" />}
                Reject
              </button>
              <button
                type="button"
                onClick={() => handleResolve(approval.approval_id, "approve")}
                disabled={resolvingId === approval.approval_id}
                className="flex items-center gap-1 rounded-md bg-emerald-600 px-2.5 py-1.5 font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
              >
                {resolvingId === approval.approval_id ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
                Approve
              </button>
            </div>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[10.5px] text-gray-600">
        "Reviewing as" is self-reported — there's no authentication system, so this isn't a verified second reviewer.
      </p>
    </div>
  );
}
