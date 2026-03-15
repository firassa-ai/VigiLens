import type { Belief, SignalPoint } from "../types/shared";

export interface ResolveSpotlightSignalInput {
  currentQuarterPoints: SignalPoint[];
  previousQuarterPoints: SignalPoint[];
}

export interface AutoEvidenceQuestionInput {
  drugId: string;
  event: string;
}

export interface PickBeliefPairInput {
  beliefs: Belief[];
  activeQuarter: string;
  loadedQuarters: string[];
}

export interface PickBeliefPairForQuartersInput {
  beliefs: Belief[];
  beforeQuarter: string;
  afterQuarter: string;
}

export interface BeliefPair {
  beforeId: string;
  afterId: string;
}

function numericOrFallback(value: number | null, fallback: number): number {
  if (value === null || Number.isNaN(value)) {
    return fallback;
  }
  return value;
}

function compareSignalStrength(a: SignalPoint, b: SignalPoint): number {
  const aLower = numericOrFallback(a.ror_ci_lower, Number.NEGATIVE_INFINITY);
  const bLower = numericOrFallback(b.ror_ci_lower, Number.NEGATIVE_INFINITY);
  if (aLower !== bLower) {
    return bLower - aLower;
  }

  const aRor = numericOrFallback(a.ror, Number.NEGATIVE_INFINITY);
  const bRor = numericOrFallback(b.ror, Number.NEGATIVE_INFINITY);
  if (aRor !== bRor) {
    return bRor - aRor;
  }

  if (a.report_count !== b.report_count) {
    return b.report_count - a.report_count;
  }

  if (a.cumulative_count !== b.cumulative_count) {
    return b.cumulative_count - a.cumulative_count;
  }

  return a.adverse_event.localeCompare(b.adverse_event);
}

function pickStrongest(points: SignalPoint[]): SignalPoint | null {
  if (points.length === 0) {
    return null;
  }
  return [...points].sort(compareSignalStrength)[0] ?? null;
}

function isEmergingTrajectory(trajectory: SignalPoint["trajectory"]): boolean {
  return trajectory === "emerging" || trajectory === "accelerating";
}

export function resolveSpotlightSignal({
  currentQuarterPoints,
  previousQuarterPoints,
}: ResolveSpotlightSignalInput): string | null {
  if (currentQuarterPoints.length === 0) {
    return null;
  }

  const previousDetected = new Set(
    previousQuarterPoints
      .filter((point) => point.signal_detected)
      .map((point) => point.adverse_event),
  );

  const newlyDetected = currentQuarterPoints.filter(
    (point) => point.signal_detected && !previousDetected.has(point.adverse_event),
  );
  const strongestNewlyDetected = pickStrongest(newlyDetected);
  if (strongestNewlyDetected) {
    return strongestNewlyDetected.adverse_event;
  }

  const emergingDetected = currentQuarterPoints.filter(
    (point) => point.signal_detected && isEmergingTrajectory(point.trajectory),
  );
  const strongestEmergingDetected = pickStrongest(emergingDetected);
  if (strongestEmergingDetected) {
    return strongestEmergingDetected.adverse_event;
  }

  const detected = currentQuarterPoints.filter((point) => point.signal_detected);
  const strongestDetected = pickStrongest(detected);
  if (strongestDetected) {
    return strongestDetected.adverse_event;
  }

  return pickStrongest(currentQuarterPoints)?.adverse_event ?? null;
}

export function buildAutoEvidenceQuestion({ drugId, event }: AutoEvidenceQuestionInput): string {
  return `What report-level evidence supports the ${event} safety signal for ${drugId}? Prioritize serious and hospitalization cases.`;
}

function isGiMotilityQuestion(text: string): boolean {
  const lowered = text.toLowerCase();
  return lowered.includes("gi motility") || lowered.includes("gastrointestinal") || lowered.includes("gastroparesis");
}

function pickLatestBeliefByQuestion(beliefs: Belief[]): Map<string, Belief> {
  const byQuestionHash = new Map<string, Belief>();
  for (const belief of beliefs) {
    const current = byQuestionHash.get(belief.question_hash);
    if (!current || current.created_at < belief.created_at) {
      byQuestionHash.set(belief.question_hash, belief);
    }
  }
  return byQuestionHash;
}

function chooseQuestionHash(
  commonHashes: string[],
  currentByHash: Map<string, Belief>,
  previousByHash: Map<string, Belief>,
): string | null {
  if (commonHashes.length === 0) {
    return null;
  }

  const giPreferredHash = commonHashes.find((questionHash) => {
    const current = currentByHash.get(questionHash);
    const previous = previousByHash.get(questionHash);
    return Boolean(
      (current && isGiMotilityQuestion(current.question_text)) ||
        (previous && isGiMotilityQuestion(previous.question_text)),
    );
  });

  if (giPreferredHash) {
    return giPreferredHash;
  }

  return [...commonHashes].sort((a, b) => {
    const aQuestion = currentByHash.get(a)?.question_text ?? "";
    const bQuestion = currentByHash.get(b)?.question_text ?? "";
    return aQuestion.localeCompare(bQuestion);
  })[0] ?? null;
}

export function pickBeliefPairForQuarterDiff({
  beliefs,
  activeQuarter,
  loadedQuarters,
}: PickBeliefPairInput): BeliefPair | null {
  const currentIndex = loadedQuarters.indexOf(activeQuarter);
  if (currentIndex <= 0) {
    return null;
  }

  const previousQuarter = loadedQuarters[currentIndex - 1];
  const currentBeliefs = beliefs.filter((belief) => belief.quarter_context === activeQuarter);
  const previousBeliefs = beliefs.filter((belief) => belief.quarter_context === previousQuarter);

  if (currentBeliefs.length === 0 || previousBeliefs.length === 0) {
    return null;
  }

  const currentByHash = pickLatestBeliefByQuestion(currentBeliefs);
  const previousByHash = pickLatestBeliefByQuestion(previousBeliefs);

  const commonHashes = [...currentByHash.keys()].filter((questionHash) => previousByHash.has(questionHash));
  const chosenHash = chooseQuestionHash(commonHashes, currentByHash, previousByHash);
  if (!chosenHash) {
    return null;
  }

  const before = previousByHash.get(chosenHash);
  const after = currentByHash.get(chosenHash);
  if (!before || !after) {
    return null;
  }

  return {
    beforeId: before.id,
    afterId: after.id,
  };
}

export function pickBeliefPairForQuarters({
  beliefs,
  beforeQuarter,
  afterQuarter,
}: PickBeliefPairForQuartersInput): BeliefPair | null {
  const beforeBeliefs = beliefs.filter((belief) => belief.quarter_context === beforeQuarter);
  const afterBeliefs = beliefs.filter((belief) => belief.quarter_context === afterQuarter);
  if (beforeBeliefs.length === 0 || afterBeliefs.length === 0) {
    return null;
  }

  const beforeByHash = pickLatestBeliefByQuestion(beforeBeliefs);
  const afterByHash = pickLatestBeliefByQuestion(afterBeliefs);
  const commonHashes = [...afterByHash.keys()].filter((questionHash) => beforeByHash.has(questionHash));
  const chosenHash = chooseQuestionHash(commonHashes, afterByHash, beforeByHash);
  if (!chosenHash) {
    return null;
  }

  const before = beforeByHash.get(chosenHash);
  const after = afterByHash.get(chosenHash);
  if (!before || !after) {
    return null;
  }

  return {
    beforeId: before.id,
    afterId: after.id,
  };
}
