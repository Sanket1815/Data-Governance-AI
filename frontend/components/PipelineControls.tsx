"use client";

import { AlertCircle, CheckCircle2, Loader2, PlayCircle } from "lucide-react";
import clsx from "clsx";
import { MetricsResponse, PipelineRunStatus } from "@/lib/anomalyTypes";
import { formatTimestamp } from "@/lib/anomalyApi";

interface PipelineControlsProps {
  metrics: MetricsResponse | null;
  isTriggering: boolean;
  triggerError: string | null;
  onTriggerRun: () => void;
}

function durationLabel(startedAt: string, completedAt: string | null): string {
  if (!completedAt) return "—";
  const ms = new Date(completedAt).getTime() - new Date(startedAt).getTime();
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

const RUN_STATUS_STYLES: Record<PipelineRunStatus, string> = {
  RUNNING: "bg-indigo-500/15 text-indigo-400",
  SUCCESS: "bg-emerald-500/15 text-emerald-400",
  FAILED: "bg-red-500/15 text-red-400",
};

export default function PipelineControls({
  metrics,
  isTriggering,
  triggerError,
  onTriggerRun,
}: PipelineControlsProps) {
  const latestRun = metrics?.latest_run ?? null;
  const isRunning = isTriggering || latestRun?.status === "RUNNING";

  const statusLabel = isRunning ? "Running" : latestRun ? (latestRun.status === "SUCCESS" ? "Idle" : "Failed") : "Not yet run";
  const statusDotClass = isRunning
    ? "bg-indigo-400 animate-pulse"
    : latestRun?.status === "FAILED"
      ? "bg-red-400"
      : latestRun?.status === "SUCCESS"
        ? "bg-emerald-400"
        : "bg-gray-600";

  return (
    <div className="rounded-xl border border-surface-border bg-surface-raised p-4">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-surface-border pb-4">
        <div className="flex items-center gap-2.5">
          <span className={clsx("h-2 w-2 rounded-full", statusDotClass)} aria-hidden="true" />
          <div>
            <div className="text-sm font-medium text-gray-200">Pipeline status: {statusLabel}</div>
            <div className="text-xs text-gray-500">
              {latestRun
                ? `Last run ${formatTimestamp(latestRun.started_at)} · ${latestRun.total_claims_scored ?? 0} claims scored`
                : "Feature refresh, IsolationForest training, and scoring have not run yet."}
            </div>
          </div>
        </div>

        <button
          type="button"
          onClick={onTriggerRun}
          disabled={isRunning}
          className={clsx(
            "flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition",
            "bg-indigo-600 text-white hover:bg-indigo-500",
            "disabled:cursor-not-allowed disabled:bg-gray-700 disabled:text-gray-400"
          )}
        >
          {isRunning ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              Retraining...
            </>
          ) : (
            <>
              <PlayCircle className="h-4 w-4" aria-hidden="true" />
              Retrain Model
            </>
          )}
        </button>
      </div>

      {triggerError && (
        <div className="mt-4 flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          {triggerError}
        </div>
      )}

      <div className="mt-4">
        <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-gray-500">Run history</h3>
        {!metrics?.recent_runs.length ? (
          <p className="py-4 text-center text-xs text-gray-600">No runs recorded yet.</p>
        ) : (
          <div className="scrollbar-thin overflow-x-auto">
            <table className="w-full min-w-max text-left text-xs">
              <thead>
                <tr className="text-gray-500">
                  <th className="py-1.5 pr-4 font-medium">Run ID</th>
                  <th className="py-1.5 pr-4 font-medium">Started</th>
                  <th className="py-1.5 pr-4 font-medium">Duration</th>
                  <th className="py-1.5 pr-4 font-medium">Status</th>
                  <th className="py-1.5 pr-4 font-medium">Claims</th>
                  <th className="py-1.5 font-medium">Anomalies</th>
                </tr>
              </thead>
              <tbody>
                {metrics.recent_runs.map((run) => (
                  <tr key={run.run_id} className="border-t border-surface-border/60 text-gray-300">
                    <td className="whitespace-nowrap py-2 pr-4 font-mono text-[11px] text-gray-400">{run.run_id}</td>
                    <td className="whitespace-nowrap py-2 pr-4">{formatTimestamp(run.started_at)}</td>
                    <td className="whitespace-nowrap py-2 pr-4">{durationLabel(run.started_at, run.completed_at)}</td>
                    <td className="whitespace-nowrap py-2 pr-4">
                      <span className={clsx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium", RUN_STATUS_STYLES[run.status])}>
                        {run.status === "SUCCESS" && <CheckCircle2 className="h-3 w-3" aria-hidden="true" />}
                        {run.status}
                      </span>
                    </td>
                    <td className="whitespace-nowrap py-2 pr-4">{run.total_claims_scored ?? "—"}</td>
                    <td className="whitespace-nowrap py-2">{run.anomalies_flagged ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
