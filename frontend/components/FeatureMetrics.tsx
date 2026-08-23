"use client";

import { AlertTriangle, CheckCircle2, Clock, ShieldAlert, XCircle } from "lucide-react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import clsx from "clsx";
import { MetricsResponse, ReviewStatus } from "@/lib/anomalyTypes";

interface FeatureMetricsProps {
  metrics: MetricsResponse | null;
  isLoading: boolean;
}

const STATUS_META: Record<
  ReviewStatus,
  { label: string; icon: typeof Clock; badgeClass: string }
> = {
  PENDING_REVIEW: { label: "Pending Review", icon: Clock, badgeClass: "bg-amber-500/15 text-amber-400" },
  CONFIRMED_FRAUD: { label: "Confirmed Fraud", icon: AlertTriangle, badgeClass: "bg-red-500/15 text-red-400" },
  FALSE_POSITIVE: { label: "False Positive", icon: XCircle, badgeClass: "bg-emerald-500/15 text-emerald-400" },
  CLEARED: { label: "Cleared", icon: CheckCircle2, badgeClass: "bg-gray-500/15 text-gray-400" },
};

function StatTile({ label, value, accent }: { label: string; value: string; accent?: "critical" | "neutral" }) {
  return (
    <div className="rounded-xl border border-surface-border bg-surface-raised px-4 py-3.5">
      <div className="text-xs font-medium text-gray-500">{label}</div>
      <div
        className={clsx(
          "mt-1 text-2xl font-semibold",
          accent === "critical" ? "text-red-400" : "text-gray-100"
        )}
      >
        {value}
      </div>
    </div>
  );
}

function ChartTooltip({ active, payload }: { active?: boolean; payload?: { payload: { label: string; count: number } }[] }) {
  const entry = payload?.[0];
  if (!active || !entry) return null;
  const { label, count } = entry.payload;
  return (
    <div className="rounded-lg border border-surface-border bg-surface-raised px-3 py-2 text-xs shadow-lg">
      <div className="text-gray-400">Risk score {label}</div>
      <div className="mt-0.5 font-semibold text-gray-100">{count.toLocaleString()} claims</div>
    </div>
  );
}

export default function FeatureMetrics({ metrics, isLoading }: FeatureMetricsProps) {
  if (isLoading && !metrics) {
    return (
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-24 animate-pulse rounded-xl border border-surface-border bg-surface-raised" />
        ))}
      </div>
    );
  }

  if (!metrics || metrics.total_claims === 0) {
    return (
      <div className="flex flex-col items-center gap-2 rounded-xl border border-surface-border bg-surface-raised px-6 py-10 text-center">
        <ShieldAlert className="h-6 w-6 text-gray-600" aria-hidden="true" />
        <p className="text-sm text-gray-500">
          No feature or scoring data yet. Trigger a pipeline run to populate metrics.
        </p>
      </div>
    );
  }

  const chartData = metrics.risk_score_distribution.map((bucket) => ({
    label: `${bucket.bucket_start.toFixed(0)}-${bucket.bucket_end.toFixed(0)}`,
    count: bucket.count,
  }));

  const statusOrder: ReviewStatus[] = ["PENDING_REVIEW", "CONFIRMED_FRAUD", "FALSE_POSITIVE", "CLEARED"];

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <StatTile label="Total claims scored" value={metrics.total_claims.toLocaleString()} />
        <StatTile label="Anomalies flagged" value={metrics.total_anomalies.toLocaleString()} accent="critical" />
        <StatTile label="Anomaly flag rate" value={`${(metrics.anomaly_rate * 100).toFixed(2)}%`} />
      </div>

      <div className="rounded-xl border border-surface-border bg-surface-raised p-4">
        <h3 className="text-sm font-medium text-gray-300">Anomaly risk score distribution</h3>
        <p className="mb-2 text-xs text-gray-500">Claims bucketed by anomaly_risk_score (0-100)</p>
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} barCategoryGap={2}>
              <CartesianGrid vertical={false} stroke="#1f2937" strokeDasharray="0" />
              <XAxis
                dataKey="label"
                tick={{ fill: "#898781", fontSize: 11 }}
                axisLine={{ stroke: "#383835" }}
                tickLine={false}
              />
              <YAxis
                tick={{ fill: "#898781", fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                width={40}
                allowDecimals={false}
              />
              <Tooltip content={<ChartTooltip />} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
              <Bar dataKey="count" fill="#6366f1" radius={[4, 4, 0, 0]} maxBarSize={24} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="rounded-xl border border-surface-border bg-surface-raised p-4">
        <h3 className="mb-3 text-sm font-medium text-gray-300">Review status breakdown</h3>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {statusOrder.map((statusKey) => {
            const meta = STATUS_META[statusKey];
            const Icon = meta.icon;
            const count = metrics.review_status_counts[statusKey] ?? 0;
            return (
              <div key={statusKey} className={clsx("flex items-center gap-2.5 rounded-lg px-3 py-2.5", meta.badgeClass)}>
                <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                <div>
                  <div className="text-sm font-semibold">{count.toLocaleString()}</div>
                  <div className="text-[11px] opacity-90">{meta.label}</div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
