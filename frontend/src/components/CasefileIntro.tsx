import { useMemo, useState } from "react";

import type { CasefileSummary, PredictionVerificationStatus, TrackingJob } from "../types/shared";
import { TrackingJobStatusDetails } from "./TrackingJobStatusDetails";

function verificationStatusClasses(status: PredictionVerificationStatus): string {
  switch (status) {
    case "supported":
      return "border-emerald-500/30 bg-emerald-500/15 text-emerald-300";
    case "mixed":
      return "border-amber-500/30 bg-amber-500/15 text-amber-300";
    default:
      return "border-[var(--accent-border)] bg-black/20 text-[var(--text-primary)]";
  }
}

type VerificationCitation = NonNullable<
  NonNullable<CasefileSummary["public_forecasts"][number]["verification"]>["citations"]
>[number];

function quarterSortValue(quarter: string): number {
  const match = /^(\d{4})-Q([1-4])$/.exec(quarter);
  if (!match) {
    return -1;
  }
  return Number(match[1]) * 10 + Number(match[2]);
}

function sourceDateToQuarter(value: string | null | undefined): string | null {
  if (!value) {
    return null;
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }
  const quarter = Math.floor(parsed.getUTCMonth() / 3) + 1;
  return `${parsed.getUTCFullYear()}-Q${quarter}`;
}

function splitProofCitations(
  citations: VerificationCitation[],
  activeQuarter: string | null,
): { availableThen: VerificationCitation[]; later: VerificationCitation[] } {
  if (!activeQuarter) {
    return { availableThen: citations, later: [] };
  }
  const availableThen: VerificationCitation[] = [];
  const later: VerificationCitation[] = [];
  citations.forEach((citation) => {
    const citationQuarter = sourceDateToQuarter(citation.source_date);
    if (citationQuarter && quarterSortValue(citationQuarter) <= quarterSortValue(activeQuarter)) {
      availableThen.push(citation);
      return;
    }
    later.push(citation);
  });
  return { availableThen, later };
}

function citationLabel(citation: VerificationCitation): string {
  return citation.source_date ? `${citation.title} · ${citation.source_date}` : citation.title;
}

interface CasefileIntroProps {
  drugLabel: string;
  brandNames: string[];
  totalReports: number;
  activeQuarter: string | null;
  casefileSummary?: CasefileSummary | null;
  onRebuildFullHistory?: () => Promise<void>;
  fullHistoryJob?: TrackingJob | null;
  fullHistoryLoading?: boolean;
  fullHistoryError?: string | null;
}

const DEFAULT_VISIBLE_LABELS = 6;
const stageLabels: Record<NonNullable<CasefileSummary["stage"]>, string> = {
  baseline: "Baseline",
  emergence: "Emergence",
  escalation: "Escalation",
  receipt_validation: "Receipt / Validation",
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

function fullHistoryJobError(job: TrackingJob | null): string | null {
  if (!job || job.status !== "failed") {
    return null;
  }
  return job.error ?? "Full-history rebuild failed";
}

export function CasefileIntro({
  drugLabel,
  brandNames,
  totalReports,
  activeQuarter,
  casefileSummary = null,
  onRebuildFullHistory,
  fullHistoryJob = null,
  fullHistoryLoading = false,
  fullHistoryError = null,
}: CasefileIntroProps) {
  const [showAllLabels, setShowAllLabels] = useState(false);
  const [showAllProofSignals, setShowAllProofSignals] = useState(false);
  const [isSubmittingRebuild, setIsSubmittingRebuild] = useState(false);
  const hasHiddenLabels = brandNames.length > DEFAULT_VISIBLE_LABELS;
  const visibleLabels = showAllLabels ? brandNames : brandNames.slice(0, DEFAULT_VISIBLE_LABELS);
  const hiddenCount = Math.max(0, brandNames.length - DEFAULT_VISIBLE_LABELS);
  const fullHistoryRunning =
    fullHistoryLoading ||
    fullHistoryJob?.status === "queued" ||
    fullHistoryJob?.status === "running";
  const fullHistoryButtonDisabled = fullHistoryRunning || isSubmittingRebuild || !onRebuildFullHistory;
  const fullHistoryJobFailure = fullHistoryError ?? fullHistoryJobError(fullHistoryJob);
  const introHeadline = casefileSummary?.headline ?? `${drugLabel} is using the live VigiLens casefile shell.`;
  const introSummary =
    casefileSummary?.summary ??
    "This casefile uses the same VigiLens evidence, trajectory, and memory workflow as the semaglutide demo, but without the semaglutide-specific judge script layered on top.";
  const leadForecast = casefileSummary?.public_forecasts[0] ?? null;
  const leadVerification = leadForecast?.verification ?? null;
  const proofForecasts = useMemo(
    () => (casefileSummary?.public_forecasts ?? []).filter((item) => item.track === "proof"),
    [casefileSummary],
  );
  const proofBackedSignals =
    casefileSummary?.proof_backed_signals ??
    proofForecasts.length ??
    0;
  const additionalProofForecasts = useMemo(
    () => proofForecasts.filter((item) => item.id !== leadForecast?.id),
    [leadForecast?.id, proofForecasts],
  );
  const visibleProofForecasts = showAllProofSignals
    ? additionalProofForecasts
    : additionalProofForecasts.slice(0, 4);
  const hiddenProofForecastCount = Math.max(0, additionalProofForecasts.length - visibleProofForecasts.length);
  const leadForecastLabel = leadForecast?.track === "proof" ? "Proof-backed Signal" : "Receipt Forecast";
  const leadForecastTitle =
    leadForecast?.track === "proof"
      ? leadForecast.adverse_event
      : `${leadForecast?.adverse_event ?? ""} -> ${leadForecast?.predicted_action.replaceAll("_", " ") ?? ""}`;
  const leadCitationBuckets = splitProofCitations(leadVerification?.citations ?? [], activeQuarter);
  const leadVerificationSummary = leadVerification?.summary ?? "External verification summary unavailable.";
  const fullHistoryProgressLabel = useMemo(() => {
    if (!fullHistoryJob) {
      return null;
    }
    return rebuildStepLabels[fullHistoryJob.step];
  }, [fullHistoryJob]);

  async function handleRebuildFullHistory(): Promise<void> {
    if (!onRebuildFullHistory || fullHistoryButtonDisabled) {
      return;
    }
    setIsSubmittingRebuild(true);
    try {
      await onRebuildFullHistory();
    } finally {
      setIsSubmittingRebuild(false);
    }
  }

  return (
    <section className="mb-5 overflow-hidden rounded-[1.6rem] border border-[var(--border)] bg-[linear-gradient(135deg,rgba(19,18,16,0.98),rgba(33,24,18,0.92))] p-6 shadow-[0_20px_60px_rgba(0,0,0,0.26)]">
      <div className="flex flex-wrap items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.2em] text-[var(--text-tertiary)]">
        <span className="rounded-full border border-[var(--accent-border)] bg-[var(--accent-dim)] px-3 py-1 text-[var(--accent)]">
          Live Casefile
        </span>
        <span className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1">
          Viewing {activeQuarter ?? "baseline"}
        </span>
        <span className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1">
          {totalReports.toLocaleString("en-US")} suspect reports
        </span>
        {casefileSummary ? (
          <span className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1">
            {stageLabels[casefileSummary.stage]}
          </span>
        ) : null}
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1.25fr)_minmax(260px,0.75fr)]">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-[var(--text-tertiary)]">
            Selected Drug
          </p>
          <h2 className="mt-2 font-display text-[clamp(2rem,4vw,3.2rem)] leading-[0.96] text-[var(--text-primary)]">
            {drugLabel}
          </h2>
          <p className="mt-3 text-[11px] font-semibold uppercase tracking-[0.22em] text-[var(--text-tertiary)]">
            {introHeadline}
          </p>
          <p className="mt-3 max-w-4xl text-sm leading-relaxed text-[var(--text-secondary)]">{introSummary}</p>
          {casefileSummary ? (
            <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <div className="rounded-[1rem] border border-white/10 bg-white/[0.04] p-3">
                <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--text-tertiary)]">
                  Lead Family
                </p>
                <p className="mt-2 text-sm text-[var(--text-primary)]">
                  {casefileSummary.lead_family ?? casefileSummary.lead_signal?.adverse_event ?? "Baseline monitoring"}
                </p>
              </div>
              <div className="rounded-[1rem] border border-white/10 bg-white/[0.04] p-3">
                <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--text-tertiary)]">
                  Validated Receipts
                </p>
                <p className="mt-2 text-sm text-[var(--text-primary)]">{casefileSummary.validated_receipts}</p>
              </div>
              <div className="rounded-[1rem] border border-white/10 bg-white/[0.04] p-3">
                <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--text-tertiary)]">
                  Pending Receipt Forecasts
                </p>
                <p className="mt-2 text-sm text-[var(--text-primary)]">{casefileSummary.pending_receipts}</p>
              </div>
              <div className="rounded-[1rem] border border-white/10 bg-white/[0.04] p-3">
                <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--text-tertiary)]">
                  Proof-backed Signals
                </p>
                <p className="mt-2 text-sm text-[var(--text-primary)]">{proofBackedSignals}</p>
              </div>
            </div>
          ) : null}
          {casefileSummary ? (
            <p className="mt-3 text-xs leading-relaxed text-[var(--text-tertiary)]">
              Receipt ledger: {casefileSummary.receipt_summary}
            </p>
          ) : null}
          {leadForecast ? (
            <div className="mt-4 rounded-[1.1rem] border border-[var(--accent-border)] bg-[var(--accent-dim)]/70 p-4">
              <div className="flex flex-wrap items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--accent)]">
                <span className={leadForecast?.track === "proof" ? "text-emerald-300" : undefined}>{leadForecastLabel}</span>
                {leadVerification ? (
                  <span className={`rounded-full px-2 py-0.5 ${verificationStatusClasses(leadVerification.status)}`}>
                    {leadVerification.status.replaceAll("_", " ")}
                  </span>
                ) : null}
                {leadForecast.novelty_status ? (
                  <span className="rounded-full border border-white/10 bg-black/20 px-2 py-0.5 text-[var(--text-secondary)]">
                    {leadForecast.novelty_status.replaceAll("_", " ")}
                  </span>
                ) : null}
              </div>
              <p className="mt-2 text-sm text-[var(--text-primary)]">{leadForecastTitle}</p>
              <p className="mt-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--text-tertiary)]">
                Detected by VigiLens: {leadForecast.created_at_quarter}
              </p>
              <p className="mt-2 text-xs leading-relaxed text-[var(--text-secondary)]">
                {leadVerificationSummary}
              </p>
              <div className="mt-3 space-y-3">
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--text-tertiary)]">
                    Available at the time
                  </p>
                  {leadCitationBuckets.availableThen.length > 0 ? (
                    <div className="mt-2 flex flex-wrap gap-2">
                      {leadCitationBuckets.availableThen.slice(0, 3).map((citation) => (
                        <a
                          key={`then:${citation.url}`}
                          href={citation.url}
                          target="_blank"
                          rel="noreferrer"
                          className="rounded-full border border-white/10 bg-black/20 px-3 py-1 text-xs text-[var(--accent)] underline decoration-[var(--accent)]/30 hover:decoration-[var(--accent)]"
                        >
                          {citationLabel(citation)}
                        </a>
                      ))}
                    </div>
                  ) : (
                    <p className="mt-2 text-xs leading-relaxed text-[var(--text-secondary)]">
                      No dated public corroboration was available by {activeQuarter ?? casefileSummary?.viewed_quarter}.
                    </p>
                  )}
                </div>
                {leadCitationBuckets.later.length > 0 ? (
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--text-tertiary)]">
                      Later corroboration
                    </p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {leadCitationBuckets.later.slice(0, 3).map((citation) => (
                        <a
                          key={`later:${citation.url}`}
                          href={citation.url}
                          target="_blank"
                          rel="noreferrer"
                          className="rounded-full border border-white/10 bg-black/20 px-3 py-1 text-xs text-[var(--accent)] underline decoration-[var(--accent)]/30 hover:decoration-[var(--accent)]"
                        >
                          {citationLabel(citation)}
                        </a>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            </div>
          ) : null}
          {visibleProofForecasts.length > 0 ? (
            <div className="mt-4 rounded-[1.1rem] border border-white/10 bg-black/20 p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--text-tertiary)]">
                    Proof-backed Predictions
                  </p>
                  <p className="mt-1 text-xs text-[var(--text-secondary)]">
                    External evidence for this drug, rendered as a clear prediction list with citations.
                  </p>
                </div>
                {hiddenProofForecastCount > 0 ? (
                  <button
                    type="button"
                    onClick={() => setShowAllProofSignals((value) => !value)}
                    className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--text-secondary)] transition hover:border-[var(--accent-border)] hover:text-[var(--accent)]"
                  >
                    {showAllProofSignals ? "Show Less" : `Show All ${additionalProofForecasts.length}`}
                  </button>
                ) : null}
              </div>
              <div className="mt-4 grid gap-3 xl:grid-cols-2">
                {visibleProofForecasts.map((forecast) => {
                  const citationBuckets = splitProofCitations(forecast.verification?.citations ?? [], activeQuarter);
                  return (
                    <div
                      key={forecast.id}
                      className="rounded-[1rem] border border-white/10 bg-white/[0.03] p-4"
                    >
                      <div className="flex flex-wrap items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--accent)]">
                        <span className="text-emerald-300">Proof-backed Signal</span>
                        {forecast.verification ? (
                          <span className={`rounded-full px-2 py-0.5 ${verificationStatusClasses(forecast.verification.status)}`}>
                            {forecast.verification.status.replaceAll("_", " ")}
                          </span>
                        ) : null}
                        {forecast.novelty_status ? (
                          <span className="rounded-full border border-white/10 bg-black/20 px-2 py-0.5 text-[var(--text-secondary)]">
                            {forecast.novelty_status.replaceAll("_", " ")}
                          </span>
                        ) : null}
                      </div>
                      <p className="mt-2 text-sm text-[var(--text-primary)]">{forecast.adverse_event}</p>
                      <p className="mt-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--text-tertiary)]">
                        Detected by VigiLens: {forecast.created_at_quarter}
                      </p>
                      <p className="mt-2 text-xs leading-relaxed text-[var(--text-secondary)]">
                        {forecast.verification?.summary ?? "External verification summary unavailable."}
                      </p>
                      <div className="mt-3 space-y-3">
                        <div>
                          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--text-tertiary)]">
                            Available at the time
                          </p>
                          {citationBuckets.availableThen.length > 0 ? (
                            <div className="mt-2 flex flex-wrap gap-2">
                              {citationBuckets.availableThen.slice(0, 3).map((citation) => (
                                <a
                                  key={`${forecast.id}:then:${citation.url}`}
                                  href={citation.url}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="rounded-full border border-white/10 bg-black/20 px-3 py-1 text-xs text-[var(--accent)] underline decoration-[var(--accent)]/30 hover:decoration-[var(--accent)]"
                                >
                                  {citationLabel(citation)}
                                </a>
                              ))}
                            </div>
                          ) : (
                            <p className="mt-2 text-xs leading-relaxed text-[var(--text-secondary)]">
                              No dated public corroboration was available by {activeQuarter ?? casefileSummary?.viewed_quarter}.
                            </p>
                          )}
                        </div>
                        {citationBuckets.later.length > 0 ? (
                          <div>
                            <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--text-tertiary)]">
                              Later corroboration
                            </p>
                            <div className="mt-2 flex flex-wrap gap-2">
                              {citationBuckets.later.slice(0, 3).map((citation) => (
                                <a
                                  key={`${forecast.id}:later:${citation.url}`}
                                  href={citation.url}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="rounded-full border border-white/10 bg-black/20 px-3 py-1 text-xs text-[var(--accent)] underline decoration-[var(--accent)]/30 hover:decoration-[var(--accent)]"
                                >
                                  {citationLabel(citation)}
                                </a>
                              ))}
                            </div>
                          </div>
                        ) : null}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ) : null}
          {casefileSummary && (casefileSummary.watchlist_alerts.length > 0 || casefileSummary.key_label_gaps.length > 0) ? (
            <div className="mt-4 rounded-[1.1rem] border border-white/10 bg-black/20 p-4">
              <div className="flex flex-wrap gap-6">
                {casefileSummary.watchlist_alerts.length > 0 ? (
                  <div className="min-w-[240px] flex-1">
                    <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--text-tertiary)]">
                      Active Watchlist
                    </p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {casefileSummary.watchlist_alerts.slice(0, 4).map((item) => (
                        <span
                          key={`${item.adverse_event}:${item.quarter}`}
                          className="rounded-full border border-[var(--accent-border)] bg-[var(--accent-dim)] px-3 py-1 text-xs text-[var(--accent)]"
                        >
                          {item.family_label ?? item.adverse_event}
                        </span>
                      ))}
                    </div>
                  </div>
                ) : null}
                {casefileSummary.key_label_gaps.length > 0 ? (
                  <div className="min-w-[240px] flex-1">
                    <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--text-tertiary)]">
                      Label Gaps Under Review
                    </p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {casefileSummary.key_label_gaps.slice(0, 4).map((gap) => (
                        <span
                          key={gap}
                          className="rounded-full border border-red-500/20 bg-red-500/10 px-3 py-1 text-xs text-red-200"
                        >
                          {gap}
                        </span>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            </div>
          ) : null}
          {onRebuildFullHistory ? (
            <div className="mt-4 rounded-[1.2rem] border border-[var(--accent-border)] bg-[linear-gradient(140deg,rgba(212,149,106,0.1),rgba(255,255,255,0.02))] p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="max-w-2xl">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-[var(--accent)]">
                    History Expansion
                  </p>
                  <p className="mt-2 text-sm leading-relaxed text-[var(--text-secondary)]">
                    {totalReports.toLocaleString("en-US")} suspect reports are loaded right now. Pull the remaining
                    matched FAERS history and rebuild this casefile from baseline when you want the full corpus.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => void handleRebuildFullHistory()}
                  disabled={fullHistoryButtonDisabled}
                  className="shrink-0 rounded-xl border border-[var(--accent-border)] bg-[var(--accent-dim)] px-4 py-2.5 text-xs font-semibold uppercase tracking-[0.16em] text-[var(--accent)] transition hover:border-[var(--accent)] hover:text-[var(--text-primary)] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {fullHistoryRunning ? "Downloading Full History..." : "Download Full History & Rebuild"}
                </button>
              </div>

              <p className="mt-2 text-[11px] leading-relaxed text-[var(--text-tertiary)]">
                API key recommended for large live pulls. This rebuild only affects this tracked drug.
              </p>

              {fullHistoryRunning && fullHistoryJob ? (
                <div className="mt-3 space-y-1.5">
                  <div className="flex items-center justify-between text-xs text-[var(--text-secondary)]">
                    <span>{fullHistoryProgressLabel}</span>
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
                  Full history loaded. The casefile has been rebuilt from the expanded evidence store.
                </p>
              ) : null}

              {fullHistoryJobFailure && !fullHistoryRunning ? (
                <p className="mt-3 rounded-md border border-red-500/20 bg-[var(--danger-dim)] px-3 py-2 text-xs text-red-300">
                  {fullHistoryJobFailure}
                </p>
              ) : null}
            </div>
          ) : null}
        </div>

        <div className="rounded-[1.25rem] border border-white/10 bg-black/20 p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-[var(--text-tertiary)]">
                Known Labels
              </p>
              {brandNames.length > 0 ? (
                <p className="mt-2 text-xs leading-relaxed text-[var(--text-secondary)]">
                  Captured brand and marketed label variants associated with this tracked drug.
                </p>
              ) : null}
            </div>
            {hasHiddenLabels ? (
              <button
                type="button"
                onClick={() => setShowAllLabels((current) => !current)}
                className="shrink-0 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--accent)] transition hover:border-[var(--accent-border)] hover:text-[var(--text-primary)]"
              >
                {showAllLabels ? "Show less" : `+${hiddenCount} more`}
              </button>
            ) : null}
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {brandNames.length > 0 ? (
              visibleLabels.map((brand) => (
                <span
                  key={brand}
                  className="rounded-full border border-white/10 bg-white/[0.05] px-3 py-1 text-xs text-[var(--text-secondary)]"
                >
                  {brand}
                </span>
              ))
            ) : (
              <p className="text-sm text-[var(--text-secondary)]">No brand names captured yet.</p>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
