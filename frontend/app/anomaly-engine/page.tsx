"use client";

import { ShieldAlert } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import AnalystReviewQueue from "@/components/AnalystReviewQueue";
import FeatureMetrics from "@/components/FeatureMetrics";
import PipelineControls from "@/components/PipelineControls";
import { getClaimsForReview, getMetrics, triggerPipelineRun, updateClaimStatus } from "@/lib/anomalyApi";
import { AnomalyApiError, ClaimReviewItem, MetricsResponse, ReviewStatus } from "@/lib/anomalyTypes";

const POLL_INTERVAL_MS = 8000;

export default function AnomalyEnginePage() {
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null);
  const [isLoadingMetrics, setIsLoadingMetrics] = useState(true);

  const [reviewItems, setReviewItems] = useState<ClaimReviewItem[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [isLoadingReview, setIsLoadingReview] = useState(true);
  const [reviewError, setReviewError] = useState<string | null>(null);

  const [isTriggering, setIsTriggering] = useState(false);
  const [triggerError, setTriggerError] = useState<string | null>(null);
  const [updatingClaimId, setUpdatingClaimId] = useState<string | null>(null);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refreshMetrics = useCallback(async () => {
    try {
      const data = await getMetrics();
      setMetrics(data);
    } catch (err) {
      logFetchError("metrics", err);
    } finally {
      setIsLoadingMetrics(false);
    }
  }, []);

  const refreshReviewQueue = useCallback(async () => {
    try {
      const data = await getClaimsForReview({ reviewStatus: "PENDING_REVIEW" });
      setReviewItems(data.items);
      setTotalCount(data.total_count);
      setReviewError(null);
    } catch (err) {
      setReviewError(err instanceof AnomalyApiError ? err.message : "Failed to load the review queue.");
    } finally {
      setIsLoadingReview(false);
    }
  }, []);

  useEffect(() => {
    refreshMetrics();
    refreshReviewQueue();

    pollRef.current = setInterval(() => {
      refreshMetrics();
    }, POLL_INTERVAL_MS);

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [refreshMetrics, refreshReviewQueue]);

  const handleTriggerRun = useCallback(async () => {
    setIsTriggering(true);
    setTriggerError(null);
    try {
      await triggerPipelineRun();
      // Give the background run a moment to reach BigQuery before the first poll.
      window.setTimeout(refreshMetrics, 1500);
    } catch (err) {
      setTriggerError(err instanceof AnomalyApiError ? err.message : "Failed to start the pipeline run.");
    } finally {
      setIsTriggering(false);
    }
  }, [refreshMetrics]);

  const handleUpdateStatus = useCallback(
    async (claimId: string, reviewStatus: ReviewStatus) => {
      setUpdatingClaimId(claimId);
      try {
        await updateClaimStatus(claimId, reviewStatus);
        setReviewItems((prev) => prev.filter((item) => item.claim_id !== claimId));
        setTotalCount((prev) => Math.max(0, prev - 1));
        refreshMetrics();
      } catch (err) {
        setReviewError(err instanceof AnomalyApiError ? err.message : "Failed to update claim status.");
      } finally {
        setUpdatingClaimId(null);
      }
    },
    [refreshMetrics]
  );

  return (
    <main className="mx-auto max-w-6xl px-6 py-10">
      <header className="mb-8 flex items-center gap-3">
        <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-red-500/15">
          <ShieldAlert className="h-5 w-5 text-red-400" aria-hidden="true" />
        </div>
        <div>
          <h1 className="text-xl font-semibold text-gray-100">Payment Integrity Anomaly Engine</h1>
          <p className="text-sm text-gray-500">
            IsolationForest-driven FWA detection over <code className="text-gray-400">healthcare_insurance</code> claims.
          </p>
        </div>
      </header>

      <div className="space-y-8">
        <section>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500">
            Pipeline &amp; Model Control
          </h2>
          <PipelineControls
            metrics={metrics}
            isTriggering={isTriggering}
            triggerError={triggerError}
            onTriggerRun={handleTriggerRun}
          />
        </section>

        <section>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500">Feature &amp; Score Metrics</h2>
          <FeatureMetrics metrics={metrics} isLoading={isLoadingMetrics} />
        </section>

        <section>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500">Incident Management</h2>
          <AnalystReviewQueue
            items={reviewItems}
            totalCount={totalCount}
            isLoading={isLoadingReview}
            error={reviewError}
            updatingClaimId={updatingClaimId}
            onUpdateStatus={handleUpdateStatus}
          />
        </section>
      </div>
    </main>
  );
}

function logFetchError(label: string, err: unknown): void {
  if (err instanceof AnomalyApiError) {
    console.error(`Failed to load ${label}: ${err.message}`);
  } else {
    console.error(`Failed to load ${label}.`, err);
  }
}
