import { useMemo } from "react";

import { buildEventLogMemoryId } from "../lib/memoryProvenance";
import type { FAERSReport, ScorecardEntry, SignalPoint } from "../types/shared";

export interface EvidenceSpotlightProps {
  activeQuarter: string | null;
  evidence: FAERSReport[];
  signalSnapshot: SignalPoint[];
  scorecard: ScorecardEntry[];
  topSignal: SignalPoint | null;
  reinterpretedReportIds?: string[];
  onOpenEvidence?: (reportId: string) => void;
  onOpenEventLogMemory?: (memoryId: string, report: FAERSReport) => void;
  drugId?: string;
  showMemorySources?: boolean;
  loading?: boolean;
  emptyMessage?: string;
  focusEvent?: string | null;
}

type ReactionTag = {
  reaction: string;
  tone: "emerging" | "stable" | "neutral";
};

function normalize(value: string): string {
  return value.trim().toLowerCase();
}

function formatDate(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleDateString("en-US", {
    month: "long",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

function monthsBetween(startIso: string, endIso: string): number | null {
  const start = new Date(startIso);
  const end = new Date(endIso);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()) || end < start) {
    return null;
  }
  const years = end.getUTCFullYear() - start.getUTCFullYear();
  const months = end.getUTCMonth() - start.getUTCMonth();
  return years * 12 + months;
}

function reportPriorityScore(
  report: FAERSReport,
  signalSnapshot: SignalPoint[],
  reinterpretedSet: Set<string>,
): [number, number, number, number, string] {
  const isReinterpreted = reinterpretedSet.has(report.safetyreportid) ? 1 : 0;
  const outcomes = report.outcomes.map(normalize);
  const hasHospitalization = outcomes.some((item) => item.includes("hospital"));
  const seriousHospitalized = report.serious && hasHospitalization ? 1 : 0;

  const detectedSignals = signalSnapshot
    .filter((point) => point.signal_detected)
    .map((point) => normalize(point.adverse_event));
  const overlapCount = report.reactions.filter((reaction) => detectedSignals.includes(normalize(reaction))).length;

  const timestamp = Number.isNaN(new Date(report.receivedate).getTime())
    ? 0
    : new Date(report.receivedate).getTime();

  return [isReinterpreted, seriousHospitalized, overlapCount, timestamp, report.safetyreportid];
}

function comparePriority(
  a: [number, number, number, number, string],
  b: [number, number, number, number, string],
): number {
  if (a[0] !== b[0]) {
    return b[0] - a[0];
  }
  if (a[1] !== b[1]) {
    return b[1] - a[1];
  }
  if (a[2] !== b[2]) {
    return b[2] - a[2];
  }
  if (a[3] !== b[3]) {
    return b[3] - a[3];
  }
  return a[4].localeCompare(b[4]);
}

function reactionTags(report: FAERSReport, signalSnapshot: SignalPoint[]): ReactionTag[] {
  const byReaction = new Map(signalSnapshot.map((point) => [normalize(point.adverse_event), point]));
  return report.reactions.map((reaction) => {
    const point = byReaction.get(normalize(reaction));
    if (!point || !point.signal_detected) {
      return { reaction, tone: "neutral" };
    }
    if (point.trajectory === "emerging" || point.trajectory === "accelerating") {
      return { reaction, tone: "emerging" };
    }
    if (point.trajectory === "stable") {
      return { reaction, tone: "stable" };
    }
    return { reaction, tone: "neutral" };
  });
}

const toneClass: Record<ReactionTag["tone"], string> = {
  emerging: "bg-red-500/10 text-red-300",
  stable: "bg-yellow-500/10 text-yellow-300",
  neutral: "bg-white/[0.04] text-[var(--text-secondary)]",
};

function whyItMatters(
  report: FAERSReport,
  context: {
    scorecard: ScorecardEntry[];
    reinterpretedReportIds: string[];
    signalSnapshot: SignalPoint[];
    topSignal: SignalPoint | null;
  },
): string {
  const { scorecard, reinterpretedReportIds, signalSnapshot, topSignal } = context;
  const reactionSet = new Set(report.reactions.map(normalize));
  const validated = scorecard.find(
    (entry) =>
      entry.result === "validated" &&
      reactionSet.has(normalize(entry.prediction.adverse_event)) &&
      entry.actual_fda_action,
  );
  if (validated && validated.actual_fda_action) {
    const leadMonths = monthsBetween(
      validated.prediction.predicted_date_range[0],
      validated.actual_fda_action.date,
    );
    return leadMonths === null
      ? `This report contains ${validated.prediction.adverse_event}, one of the validated signals that matched a real FDA ${validated.prediction.predicted_action} action. The agent linked this report into its evidence chain when issuing that prediction.`
      : `This report contains ${validated.prediction.adverse_event}, one of the validated signals that matched an FDA ${validated.prediction.predicted_action} about ${leadMonths} months later. The agent used this as part of the evidence chain behind its forecast.`;
  }

  if (reinterpretedReportIds.includes(report.safetyreportid)) {
    return "This report was retroactively reinterpreted after a newly detected signal emerged, showing how earlier precursor events became clinically meaningful in the agent's reasoning chain.";
  }

  const hasIleus = signalSnapshot.some(
    (point) => point.adverse_event === "Ileus" && point.signal_detected,
  );
  const hasGiPrecursor = report.reactions.some((reaction) =>
    ["Constipation", "Abdominal pain", "Abdominal distension"].includes(reaction),
  );
  if (hasIleus && hasGiPrecursor) {
    return "This report combines GI precursor reactions with an emerging severe GI context, and the agent used this pattern to support a broader motility disruption assessment.";
  }

  if (topSignal) {
    const ror = topSignal.ror === null || Number.isNaN(topSignal.ror) ? "-" : topSignal.ror.toFixed(2);
    return `This report contributes to the ${topSignal.adverse_event} signal, currently tracking at ROR ${ror}, and reinforces the agent's current quarter risk interpretation.`;
  }

  return "This report adds patient-level evidence to the active surveillance timeline.";
}

export function EvidenceSpotlight({
  activeQuarter,
  evidence,
  signalSnapshot,
  scorecard,
  topSignal,
  reinterpretedReportIds = [],
  onOpenEvidence,
  onOpenEventLogMemory,
  drugId = "",
  showMemorySources = false,
  loading = false,
  emptyMessage = "No report-level evidence found for this quarter yet.",
  focusEvent = null,
}: EvidenceSpotlightProps) {
  const reinterpretedSet = useMemo(() => new Set(reinterpretedReportIds), [reinterpretedReportIds]);

  const selected = useMemo(() => {
    if (evidence.length === 0) {
      return null;
    }
    return [...evidence].sort((a, b) =>
      comparePriority(
        reportPriorityScore(a, signalSnapshot, reinterpretedSet),
        reportPriorityScore(b, signalSnapshot, reinterpretedSet),
      ),
    )[0];
  }, [evidence, reinterpretedSet, signalSnapshot]);

  const eventLogMemoryId = useMemo(() => {
    if (!selected) {
      return null;
    }
    return selected.eventlog_memory_id ?? buildEventLogMemoryId(drugId || "unknown", selected.safetyreportid);
  }, [drugId, selected]);

  if (!activeQuarter) {
    return null;
  }

  return (
    <section className="rounded-xl border border-[var(--border)] bg-[var(--bg-panel)] p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-xs font-medium tracking-wide text-[var(--text-tertiary)]">
          Evidence Spotlight
        </h3>
        <span className="font-mono text-xs text-[var(--text-secondary)]">
          {activeQuarter}
        </span>
      </div>

      {!selected ? (
        <p className="text-sm text-[var(--text-secondary)]">
          {loading
            ? `Loading report-level evidence${focusEvent ? ` for ${focusEvent}` : ""}\u2026`
            : emptyMessage}
        </p>
      ) : (
        <div className="space-y-3">
          <div className="rounded-lg border border-[var(--accent-border)] bg-[var(--accent-dim)] p-3">
            <p className="text-xs font-semibold tracking-wide text-[var(--accent)]">Why This Matters</p>
            <p className="mt-1 text-sm leading-relaxed text-[var(--text-secondary)]">
              {whyItMatters(selected, {
                scorecard,
                reinterpretedReportIds,
                signalSnapshot,
                topSignal,
              })}
            </p>
          </div>

          <div className="rounded-lg bg-[var(--bg-card)] p-3">
            <p className="font-mono text-sm font-medium text-[var(--text-primary)]">
              FAERS #{selected.safetyreportid}
            </p>
            <p className="mt-1 text-xs text-[var(--text-secondary)]">
              {formatDate(selected.receivedate)} &middot; {selected.patient_sex}, age {selected.patient_age ?? "unknown"}
            </p>
          </div>

          <div>
            <p className="mb-1.5 text-xs font-medium text-[var(--text-tertiary)]">Reactions</p>
            <div className="flex flex-wrap gap-1">
              {reactionTags(selected, signalSnapshot).map((tag) => (
                <span key={`${selected.safetyreportid}-${tag.reaction}`} className={`rounded-md px-2 py-0.5 text-xs ${toneClass[tag.tone]}`}>
                  {tag.reaction}
                </span>
              ))}
            </div>
          </div>

          <div className="rounded-lg bg-[var(--bg-card)] p-3">
            <p className="text-xs font-medium text-[var(--text-tertiary)]">Clinical Severity</p>
            <p className="mt-1 text-sm text-[var(--text-primary)]">
              {selected.serious ? "Serious" : "Non-serious"}
              {selected.outcomes.length > 0 ? ` \u2014 ${selected.outcomes.join(", ")}` : ""}
            </p>
          </div>

          {showMemorySources ? (
            <div className="rounded-lg bg-[var(--bg-card)] p-3 text-xs text-[var(--text-tertiary)]">
              <p>Retrieved via EverMemOS EventLog search</p>
              {eventLogMemoryId ? (
                <button
                  type="button"
                  onClick={() => onOpenEventLogMemory?.(eventLogMemoryId, selected)}
                  className="mt-1 rounded bg-white/[0.04] px-1.5 py-0.5 font-mono text-[11px] text-[var(--text-tertiary)] transition hover:bg-white/[0.08] hover:text-[var(--text-primary)]"
                >
                  {eventLogMemoryId}
                </button>
              ) : null}
            </div>
          ) : null}

          <button
            type="button"
            onClick={() => onOpenEvidence?.(selected.safetyreportid)}
            className="w-full rounded-lg bg-white/[0.04] px-3 py-2 text-xs font-medium text-[var(--text-secondary)] transition hover:bg-white/[0.08] hover:text-[var(--text-primary)]"
          >
            View full report
          </button>
        </div>
      )}
    </section>
  );
}
