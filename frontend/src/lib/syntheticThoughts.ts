import type { ScorecardEntry, SignalPoint } from "../types/shared";

export interface QuarterDeduperRef {
  current: string | null;
}

function sortSignalSnapshot(signalSnapshot: SignalPoint[]): SignalPoint[] {
  return [...signalSnapshot].sort((a, b) => {
    const aScore = a.ror_ci_lower ?? -1;
    const bScore = b.ror_ci_lower ?? -1;
    if (a.signal_detected !== b.signal_detected) {
      return Number(b.signal_detected) - Number(a.signal_detected);
    }
    if (aScore !== bScore) {
      return bScore - aScore;
    }
    return b.report_count - a.report_count;
  });
}

function formatMetric(value: number | null | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "n/a";
  }
  return value.toFixed(2);
}

export function claimQuarterOnce(ref: QuarterDeduperRef, quarter: string | null): boolean {
  if (!quarter) {
    return false;
  }
  if (ref.current === quarter) {
    return false;
  }
  ref.current = quarter;
  return true;
}

export function syntheticThoughtId(
  kind: "summary" | "observation",
  drugId: string,
  quarter: string,
): string {
  return `synthetic:${kind}:${drugId}:${quarter}`;
}

export function buildQuarterSummaryThought(
  quarter: string,
  signalSnapshot: SignalPoint[],
): string {
  const ranked = sortSignalSnapshot(signalSnapshot);
  if (ranked.length === 0) {
    return `${quarter} analysis complete. No ranked signal snapshot is available yet; monitoring continues.`;
  }

  const detectedSignals = ranked.filter((point) => point.signal_detected);
  const topSignal = ranked[0];
  const detectedLabel =
    detectedSignals.length === 1
      ? "1 active signal"
      : `${detectedSignals.length} active signals`;

  return (
    `${quarter} analysis complete. ${topSignal.adverse_event} leads current pressure ` +
    `(ROR ${formatMetric(topSignal.ror)}; CI lower ${formatMetric(topSignal.ror_ci_lower)}). ` +
    `${detectedLabel} under surveillance.`
  );
}

export function buildTimeTravelObservationThought(
  quarter: string,
  signalSnapshot: SignalPoint[],
  scorecardAsOfViewed: ScorecardEntry[],
): string {
  const ranked = sortSignalSnapshot(signalSnapshot);
  if (ranked.length === 0) {
    return `Reviewing ${quarter}: signal snapshot is still loading or unavailable for this view. Monitoring continues.`;
  }

  const detectedSignals = ranked.filter((point) => point.signal_detected);
  const topSignal = ranked[0];
  const pendingForecasts = scorecardAsOfViewed.filter((entry) => entry.result === "pending").length;
  const detectedLabel =
    detectedSignals.length === 1
      ? "1 detected signal"
      : `${detectedSignals.length} detected signals`;
  const pendingLabel =
    pendingForecasts === 0
      ? "No pending forecasts at this horizon."
      : pendingForecasts === 1
        ? "1 forecast pending validation."
        : `${pendingForecasts} forecasts pending validation.`;

  return (
    `Reviewing ${quarter}: ${detectedLabel}. ` +
    `${topSignal.adverse_event} is the leading signal (ROR ${formatMetric(topSignal.ror)}). ` +
    pendingLabel
  );
}

export function buildQuerySearchThought(question: string): string {
  return `Searching EverMemOS for query context: ${question}`;
}

export function buildQueryGroundingThought(episodicCount: number): string {
  if (episodicCount <= 0) {
    return "No episodic memories matched this query; continuing with FAERS evidence only.";
  }
  if (episodicCount === 1) {
    return "Retrieved 1 episodic memory for grounding.";
  }
  return `Retrieved ${episodicCount} episodic memories for grounding.`;
}

export function buildQueryEpisodicRecallThought(episodicCount: number): string {
  if (episodicCount <= 0) {
    return "EPISODIC recall: no quarter-matched episodic memories found; using local evidence context.";
  }
  if (episodicCount === 1) {
    return "EPISODIC recall: retrieved 1 episodic memory for grounding.";
  }
  return `EPISODIC recall: retrieved ${episodicCount} episodic memories for grounding.`;
}

export function buildQueryForesightRecallThought(foresightCount: number): string {
  if (foresightCount <= 0) {
    return "FORESIGHT recall: no linked foresight memories for this query horizon.";
  }
  if (foresightCount === 1) {
    return "FORESIGHT recall: retrieved 1 foresight memory for regulatory horizon calibration.";
  }
  return `FORESIGHT recall: retrieved ${foresightCount} foresight memories for regulatory horizon calibration.`;
}

export function buildQueryBeliefThought(quarter: string, answerText: string): string {
  const firstLine = answerText
    .split("\n")
    .map((line) => line.trim())
    .find((line) => line.length > 0);
  const summary = firstLine ?? "Belief updated.";
  return `Belief updated for ${quarter}: ${summary}`;
}
