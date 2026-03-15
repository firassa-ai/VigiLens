import { useEffect, useMemo, useState } from "react";

import type { IngestProgressMessage, IngestStatus, TrackingJob } from "../types/shared";
import { TrackingJobStatusDetails } from "./TrackingJobStatusDetails";

export interface IngestAllQuarterProgress {
  active: boolean;
  completedQuarters: number;
  totalQuarters: number | null;
}

export interface IngestButtonProps {
  status: IngestStatus | null;
  storedReportCount?: number;
  onIngest: () => Promise<void>;
  onIngestAll: () => Promise<void>;
  onCancelIngestAll?: () => void;
  onRebuildFullHistory: () => Promise<void>;
  onDismissFullHistory?: () => void;
  onReset: () => Promise<void>;
  progress: IngestProgressMessage | null;
  ingestAllProgress?: IngestAllQuarterProgress | null;
  fullHistoryJob?: TrackingJob | null;
  fullHistoryLoading?: boolean;
  fullHistoryError?: string | null;
}

const phaseLabels: Record<string, string> = {
  starting: "Initializing pipeline",
  loading_reports: "Loading evidence",
  computing_signals: "Computing ROR/PRR trajectories",
  posting_evermemos: "Posting digest",
  generating_beliefs: "Generating beliefs",
  done: "Completed",
  error: "Failed",
};

const rebuildStepLabels: Record<TrackingJob["step"], string> = {
  queued: "Queued",
  resolving_identity: "Resolving tracked identity",
  fetching_faers: "Fetching full FAERS history",
  deduping_transforming: "Deduping and transforming",
  seeding_database: "Refreshing evidence store",
  computing_baseline_stats: "Recomputing baseline",
  writing_memory: "Writing baseline memory",
  ready: "Ready",
  failed: "Failed",
};

function prettyQuarter(value: string): string {
  const match = /^(\d{4})-Q([1-4])$/.exec(value);
  if (!match) {
    return value;
  }
  return `Q${match[2]} ${match[1]}`;
}

function fullHistoryJobError(job: TrackingJob | null): string | null {
  if (!job || job.status !== "failed") {
    return null;
  }
  return job.error ?? "Full-history rebuild failed";
}

export function IngestButton({
  status,
  storedReportCount = 0,
  onIngest,
  onIngestAll,
  onCancelIngestAll,
  onRebuildFullHistory,
  onDismissFullHistory,
  onReset,
  progress,
  ingestAllProgress = null,
  fullHistoryJob = null,
  fullHistoryLoading = false,
  fullHistoryError = null,
}: IngestButtonProps) {
  const [showSuccess, setShowSuccess] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (progress?.phase !== "done") {
      return;
    }
    setShowSuccess(progress.quarter);
    const timer = window.setTimeout(() => {
      setShowSuccess(null);
    }, 1000);
    return () => {
      window.clearTimeout(timer);
    };
  }, [progress]);

  const isBusy =
    isSubmitting ||
    status?.evermemos_status === "ingesting" ||
    status?.evermemos_status === "consolidating" ||
    (progress !== null && progress.phase !== "done" && progress.phase !== "error");
  const fullHistoryRunning =
    fullHistoryLoading ||
    fullHistoryJob?.status === "queued" ||
    fullHistoryJob?.status === "running";
  const interfaceBusy = isBusy || fullHistoryRunning;

  const disabled = !status || !status.next_quarter || interfaceBusy;
  const ingestAllRunning = Boolean(ingestAllProgress?.active);
  const ingestAllDisabled = ingestAllRunning ? false : !status || !status.next_quarter || interfaceBusy;
  const rebuildDisabled = !status || interfaceBusy;
  const showDismissFullHistory =
    Boolean(onDismissFullHistory) &&
    Boolean(fullHistoryError || fullHistoryJobError(fullHistoryJob) || fullHistoryJob?.status === "ready");

  const progressPercent = useMemo(() => {
    if (!progress || progress.total_reports <= 0) {
      return 0;
    }
    return Math.min(100, Math.round((progress.reports_processed / progress.total_reports) * 100));
  }, [progress]);

  const actionLabel = status?.next_quarter
    ? `Advance ${prettyQuarter(status.next_quarter)}`
    : "No More Quarters";

  async function handleClick(): Promise<void> {
    if (disabled) {
      return;
    }
    setIsSubmitting(true);
    try {
      await onIngest();
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleReset(): Promise<void> {
    if (!status || interfaceBusy) {
      return;
    }
    setIsSubmitting(true);
    try {
      await onReset();
      setShowSuccess(null);
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleIngestAllClick(): Promise<void> {
    if (ingestAllRunning) {
      onCancelIngestAll?.();
      return;
    }
    if (ingestAllDisabled) {
      return;
    }
    setIsSubmitting(true);
    try {
      await onIngestAll();
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleRebuildFullHistory(): Promise<void> {
    if (rebuildDisabled) {
      return;
    }
    setIsSubmitting(true);
    try {
      await onRebuildFullHistory();
      setShowSuccess(null);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-panel)] p-4">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h3 className="text-xs font-medium tracking-wide text-[var(--text-tertiary)]">
            Advance Agent Timeline
          </h3>
          <p className="mt-0.5 text-xs text-[var(--text-secondary)]">
            Agent processes next quarter
          </p>
        </div>
        <span className="rounded-md bg-[var(--bg-card)] px-2 py-0.5 font-mono text-[11px] text-[var(--text-secondary)]">
          {status?.evermemos_status ?? "idle"}
        </span>
      </div>

      {status ? (
        <p className="mb-3 text-[11px] text-[var(--text-tertiary)]">
          {status.quarters_loaded.length} quarters loaded · {status.total_reports_loaded.toLocaleString("en-US")} reports analyzed
        </p>
      ) : null}

      {status ? (
        <div className="mb-3 rounded-md bg-[var(--bg-card)] px-3 py-2 text-[11px] leading-relaxed text-[var(--text-secondary)]">
          <span className="font-semibold text-[var(--text-primary)]">
            {storedReportCount.toLocaleString("en-US")} suspect reports
          </span>{" "}
          are stored locally for this drug. Use the full-history action to pull the remaining FAERS history and reset the
          casefile back to baseline.
        </div>
      ) : null}

      <button
        type="button"
        onClick={handleClick}
        disabled={disabled}
        className="group relative flex w-full items-center justify-center overflow-hidden rounded-lg bg-[var(--accent)] px-4 py-2.5 text-sm font-semibold text-[var(--bg-root)] transition hover:bg-[var(--accent-hover)] disabled:cursor-not-allowed disabled:opacity-40"
      >
        <span className="absolute inset-0 translate-x-[-120%] bg-gradient-to-r from-transparent via-white/20 to-transparent transition duration-700 group-hover:translate-x-[120%]" />
        <span className="relative">
          {showSuccess ? `Advanced ${prettyQuarter(showSuccess)}` : actionLabel}
        </span>
      </button>

      <button
        type="button"
        onClick={handleIngestAllClick}
        disabled={ingestAllDisabled}
        className="mt-2 w-full rounded-lg bg-white/[0.03] px-3 py-2 text-xs font-semibold text-[var(--text-secondary)] transition hover:bg-white/[0.06] hover:text-[var(--text-primary)] disabled:cursor-not-allowed disabled:opacity-40"
      >
        {ingestAllRunning ? "Stop Simulation" : "Run Full Simulation"}
      </button>

      {ingestAllProgress?.active ? (
        <p className="mt-2 rounded-md bg-[var(--bg-card)] px-2.5 py-1.5 text-xs text-[var(--text-secondary)]">
          Simulation progress: {ingestAllProgress.completedQuarters}/
          {ingestAllProgress.totalQuarters ?? "?"} quarters
        </p>
      ) : null}

      {progress && progress.phase !== "done" && progress.phase !== "error" ? (
        <div className="mt-3 space-y-1.5">
          <div className="flex items-center justify-between text-xs text-[var(--text-secondary)]">
            <span>{phaseLabels[progress.phase] ?? progress.phase}</span>
            <span className="font-mono">
              {progress.reports_processed}/{progress.total_reports}
            </span>
          </div>
          <div className="h-1 overflow-hidden rounded-full bg-[var(--bg-elevated)]">
            <div
              className="h-full rounded-full bg-[var(--accent)] transition-all duration-500"
              style={{ width: `${progressPercent}%` }}
            />
          </div>
        </div>
      ) : null}

      {progress?.phase === "error" ? (
        <p className="mt-3 rounded-md border border-red-500/20 bg-[var(--danger-dim)] px-3 py-2 text-xs text-red-300">
          {progress.detail ?? "Ingestion failed"}
        </p>
      ) : null}

      <button
        type="button"
        onClick={handleReset}
        disabled={!status || interfaceBusy}
        className="mt-3 w-full rounded-lg bg-white/[0.03] px-3 py-2 text-xs font-medium text-[var(--text-secondary)] transition hover:bg-white/[0.06] hover:text-[var(--text-primary)] disabled:cursor-not-allowed disabled:opacity-40"
      >
        Reset Agent Memory
      </button>

      <button
        type="button"
        onClick={handleRebuildFullHistory}
        disabled={rebuildDisabled}
        className="mt-2 w-full rounded-lg border border-[var(--accent-border)] bg-[var(--accent-dim)] px-3 py-2 text-xs font-semibold text-[var(--accent)] transition hover:border-[var(--accent)] hover:text-[var(--text-primary)] disabled:cursor-not-allowed disabled:opacity-40"
      >
        {fullHistoryRunning ? "Downloading Full History..." : "Download Full History & Rebuild"}
      </button>

      <p className="mt-2 text-[11px] leading-relaxed text-[var(--text-tertiary)]">
        This fetches the full matched FAERS history for the tracked drug, clears the current casefile analysis, and
        restarts from baseline. API key recommended for large live pulls.
      </p>

      {fullHistoryRunning && fullHistoryJob ? (
        <div className="mt-3 space-y-1.5">
          <div className="flex items-center justify-between text-xs text-[var(--text-secondary)]">
            <span>{rebuildStepLabels[fullHistoryJob.step]}</span>
            <span className="font-mono">{fullHistoryJob.progress}%</span>
          </div>
          <div className="h-1 overflow-hidden rounded-full bg-[var(--bg-elevated)]">
            <div
              className="h-full rounded-full bg-[var(--accent)] transition-all duration-500"
              style={{ width: `${Math.max(8, fullHistoryJob.progress)}%` }}
            />
          </div>
          <TrackingJobStatusDetails job={fullHistoryJob} />
        </div>
      ) : null}

      {fullHistoryJob?.status === "ready" ? (
        <p className="mt-3 rounded-md border border-emerald-500/20 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200">
          Full history loaded. The casefile was reset to baseline with the expanded evidence store.
        </p>
      ) : null}

      {(fullHistoryError || fullHistoryJobError(fullHistoryJob)) && !fullHistoryRunning ? (
        <p className="mt-3 rounded-md border border-red-500/20 bg-[var(--danger-dim)] px-3 py-2 text-xs text-red-300">
          {fullHistoryError ?? fullHistoryJobError(fullHistoryJob)}
        </p>
      ) : null}

      {showDismissFullHistory ? (
        <button
          type="button"
          onClick={onDismissFullHistory}
          className="mt-2 w-full rounded-lg bg-white/[0.03] px-3 py-2 text-xs font-medium text-[var(--text-secondary)] transition hover:bg-white/[0.06] hover:text-[var(--text-primary)]"
        >
          Dismiss Rebuild Status
        </button>
      ) : null}
    </div>
  );
}
