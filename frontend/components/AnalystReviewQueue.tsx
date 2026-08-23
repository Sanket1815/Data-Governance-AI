"use client";

import { AlertTriangle, Loader2, ShieldCheck, XCircle } from "lucide-react";
import clsx from "clsx";
import { formatCurrency, formatTimestamp } from "@/lib/anomalyApi";
import { ClaimReviewItem, ReviewStatus } from "@/lib/anomalyTypes";

interface AnalystReviewQueueProps {
  items: ClaimReviewItem[];
  totalCount: number;
  isLoading: boolean;
  error: string | null;
  updatingClaimId: string | null;
  onUpdateStatus: (claimId: string, reviewStatus: ReviewStatus) => void;
}

function riskScoreBadgeClass(score: number): string {
  if (score >= 90) return "bg-red-500/15 text-red-400";
  if (score >= 80) return "bg-orange-500/15 text-orange-400";
  return "bg-amber-500/15 text-amber-400";
}

export default function AnalystReviewQueue({
  items,
  totalCount,
  isLoading,
  error,
  updatingClaimId,
  onUpdateStatus,
}: AnalystReviewQueueProps) {
  return (
    <div className="overflow-hidden rounded-xl border border-surface-border bg-surface-raised">
      <div className="flex items-center justify-between border-b border-surface-border px-4 py-3">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-4 w-4 text-gray-400" aria-hidden="true" />
          <h3 className="text-sm font-medium text-gray-200">Analyst Review Queue</h3>
        </div>
        <span className="text-xs text-gray-500">{totalCount.toLocaleString()} claim(s) pending triage</span>
      </div>

      {error && (
        <div className="mx-4 mt-4 flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          {error}
        </div>
      )}

      {isLoading && !items.length ? (
        <div className="space-y-2 p-4">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-16 animate-pulse rounded-lg border border-surface-border bg-white/[0.02]" />
          ))}
        </div>
      ) : !items.length ? (
        <div className="px-4 py-10 text-center text-sm text-gray-500">
          No flagged claims are currently pending review.
        </div>
      ) : (
        <div className="scrollbar-thin overflow-x-auto">
          <table className="w-full min-w-max text-left text-sm">
            <thead>
              <tr className="border-b border-surface-border bg-white/[0.02] text-xs text-gray-500">
                <th className="px-4 py-2.5 font-medium">Claim</th>
                <th className="px-4 py-2.5 font-medium">Member / Plan</th>
                <th className="px-4 py-2.5 font-medium">Billed</th>
                <th className="px-4 py-2.5 font-medium">Risk Score</th>
                <th className="px-4 py-2.5 font-medium">Root-Cause Drivers</th>
                <th className="px-4 py-2.5 font-medium">Scored</th>
                <th className="px-4 py-2.5 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => {
                const isUpdating = updatingClaimId === item.claim_id;
                return (
                  <tr key={item.claim_id} className="border-b border-surface-border/60 last:border-0 align-top hover:bg-white/[0.02]">
                    <td className="whitespace-nowrap px-4 py-3">
                      <div className="font-medium text-gray-100">{item.claim_id}</div>
                      <div className="text-xs text-gray-500">{item.claim_type} · {item.claim_status}</div>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-gray-300">
                      <div>{item.member_id}</div>
                      <div className="text-xs text-gray-500">{item.plan_id}</div>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-gray-300">
                      {formatCurrency(item.total_billed_amount)}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3">
                      <span
                        className={clsx(
                          "inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold",
                          riskScoreBadgeClass(item.anomaly_risk_score)
                        )}
                      >
                        {item.anomaly_risk_score.toFixed(1)}
                      </span>
                    </td>
                    <td className="max-w-xs px-4 py-3">
                      <div className="flex flex-wrap gap-1.5">
                        {item.top_risk_drivers.map((driver, idx) => (
                          <span
                            key={idx}
                            title={`SHAP contribution: ${driver.shap_value.toFixed(3)}`}
                            className="rounded-full border border-surface-border bg-white/[0.03] px-2 py-0.5 text-[11px] text-gray-300"
                          >
                            {driver.description}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-xs text-gray-500">
                      {formatTimestamp(item.scored_at)}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3">
                      <div className="flex items-center gap-1.5">
                        <button
                          type="button"
                          disabled={isUpdating}
                          onClick={() => onUpdateStatus(item.claim_id, "CONFIRMED_FRAUD")}
                          className="flex items-center gap-1 rounded-md bg-red-500/15 px-2.5 py-1.5 text-xs font-medium text-red-400 transition hover:bg-red-500/25 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {isUpdating ? <Loader2 className="h-3 w-3 animate-spin" /> : <AlertTriangle className="h-3 w-3" />}
                          Confirm Fraud
                        </button>
                        <button
                          type="button"
                          disabled={isUpdating}
                          onClick={() => onUpdateStatus(item.claim_id, "FALSE_POSITIVE")}
                          className="flex items-center gap-1 rounded-md bg-white/5 px-2.5 py-1.5 text-xs font-medium text-gray-300 transition hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-50"
                        >
                          {isUpdating ? <Loader2 className="h-3 w-3 animate-spin" /> : <XCircle className="h-3 w-3" />}
                          Dismiss
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
