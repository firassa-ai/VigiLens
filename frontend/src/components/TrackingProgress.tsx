import type { TrackingJob } from "../types/shared";
import { TrackingJobStatusDetails } from "./TrackingJobStatusDetails";

interface TrackingProgressProps {
  job: TrackingJob | null;
  loading?: boolean;
  error?: string | null;
  onDismiss?: () => void;
}

function stepLabel(step: TrackingJob["step"]): string {
  switch (step) {
    case "queued":
      return "Queued";
    case "resolving_identity":
      return "Resolving drug identity";
    case "fetching_faers":
      return "Fetching FAERS";
    case "deduping_transforming":
      return "Deduping and transforming";
    case "seeding_database":
      return "Seeding database";
    case "computing_baseline_stats":
      return "Computing baseline";
    case "writing_memory":
      return "Writing memory";
    case "ready":
      return "Ready";
    case "failed":
      return "Failed";
  }
}

function scanLabel(job: TrackingJob): string {
  const reportLabel =
    job.options_json.max_reports === null ? "Full history" : `${job.options_json.max_reports ?? 1500} reports`;
  return `${reportLabel} / ${job.options_json.baseline_quarters ?? 4} quarters`;
}

export function TrackingProgress({
  job,
  loading = false,
  error = null,
  onDismiss,
}: TrackingProgressProps) {
  const showDismiss = Boolean(onDismiss) && Boolean(error || job?.status === "failed");

  return (
    <aside className="rounded-[1.5rem] border border-[var(--border)] bg-[linear-gradient(160deg,rgba(20,18,16,0.98),rgba(29,22,18,0.94))] p-4 shadow-[0_16px_50px_rgba(0,0,0,0.24)]">
      <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-[var(--text-tertiary)]">
        Tracking Progress
      </p>

      {loading ? <div className="mt-4 h-[320px] animate-pulse rounded-[1.1rem] bg-[var(--bg-card)]" /> : null}
      {!loading && error ? (
        <div className="mt-4 space-y-3">
          <div className="rounded-[1rem] border border-red-500/25 bg-red-500/10 px-4 py-3 text-sm text-red-200">
            {error}
          </div>
          {showDismiss ? (
            <button
              type="button"
              onClick={onDismiss}
              className="rounded-full border border-white/10 bg-white/[0.04] px-4 py-3 text-xs font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)] transition hover:bg-white/[0.08] hover:text-[var(--text-primary)]"
            >
              Back to preview
            </button>
          ) : null}
        </div>
      ) : null}
      {!loading && !error && !job ? (
        <div className="mt-4 rounded-[1.1rem] border border-dashed border-white/10 bg-black/15 px-4 py-6 text-sm leading-relaxed text-[var(--text-secondary)]">
          Start monitoring from a preview to create a persistent tracking job.
        </div>
      ) : null}

      {!loading && !error && job ? (
        <div className="mt-4 space-y-4">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--text-tertiary)]">
              Medication
            </p>
            <h2 className="mt-2 font-display text-2xl text-[var(--text-primary)]">
              {job.resolved_generic_name ?? job.medication_name}
            </h2>
            <p className="mt-2 text-sm text-[var(--text-secondary)]">
              Requested as {job.medication_name}
            </p>
          </div>

          <div className="rounded-[1.1rem] border border-white/10 bg-black/15 p-4">
            <div className="flex items-center justify-between gap-3">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">
                {stepLabel(job.step)}
              </p>
              <span className="text-xs text-[var(--text-secondary)]">{job.progress}%</span>
            </div>
            <div className="mt-3 h-2 rounded-full bg-white/10">
              <div
                className={`h-2 rounded-full transition-all ${
                  job.status === "failed" ? "bg-red-300" : "bg-[var(--accent)]"
                }`}
                style={{ width: `${Math.max(6, job.progress)}%` }}
              />
            </div>
            <TrackingJobStatusDetails job={job} />
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-[1rem] border border-white/10 bg-black/15 p-3">
              <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--text-tertiary)]">
                Status
              </p>
              <p className="mt-2 text-sm text-[var(--text-primary)]">{job.status}</p>
            </div>
            <div className="rounded-[1rem] border border-white/10 bg-black/15 p-3">
              <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--text-tertiary)]">
                Scan options
              </p>
              <p className="mt-2 text-sm text-[var(--text-primary)]">{scanLabel(job)}</p>
            </div>
          </div>

          {job.error ? (
            <div className="rounded-[1rem] border border-red-500/25 bg-red-500/10 px-4 py-3 text-sm leading-relaxed text-red-200">
              {job.error}
            </div>
          ) : null}

          {showDismiss && !error ? (
            <button
              type="button"
              onClick={onDismiss}
              className="rounded-full border border-white/10 bg-white/[0.04] px-4 py-3 text-xs font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)] transition hover:bg-white/[0.08] hover:text-[var(--text-primary)]"
            >
              Back to preview
            </button>
          ) : null}
        </div>
      ) : null}
    </aside>
  );
}
