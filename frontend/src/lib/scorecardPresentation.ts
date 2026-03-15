import type { ScorecardEntry } from "../types/shared";

export type ScorecardPresentationMode = "demo" | "generic";

export interface ScorecardDisplayCounts {
  validated: number;
  pending: number;
  early: number;
  missed: number;
  active: number;
  total: number;
}

export function splitScorecardEntries(
  entries: ScorecardEntry[],
  presentationMode: ScorecardPresentationMode,
): { activeEntries: ScorecardEntry[]; archivedEntries: ScorecardEntry[] } {
  if (presentationMode !== "demo") {
    return {
      activeEntries: entries,
      archivedEntries: [],
    };
  }

  return {
    activeEntries: entries.filter((entry) => entry.result !== "missed"),
    archivedEntries: entries.filter((entry) => entry.result === "missed"),
  };
}

export function countScorecardEntries(
  entries: ScorecardEntry[],
): ScorecardDisplayCounts {
  const counts = entries.reduce<ScorecardDisplayCounts>(
    (acc, entry) => {
      acc.total += 1;
      if (entry.result === "validated") {
        acc.validated += 1;
      } else if (entry.result === "pending") {
        acc.pending += 1;
      } else if (entry.result === "early") {
        acc.early += 1;
      } else if (entry.result === "missed") {
        acc.missed += 1;
      }
      return acc;
    },
    {
      validated: 0,
      pending: 0,
      early: 0,
      missed: 0,
      active: 0,
      total: 0,
    },
  );

  counts.active = counts.validated + counts.pending + counts.early;
  return counts;
}

export function buildDemoReceiptMetricSuffix(
  counts: Pick<ScorecardDisplayCounts, "pending" | "early">,
): string {
  const segments = ["validated"];
  if (counts.pending > 0) {
    segments.push(`${counts.pending} pending`);
  }
  if (counts.early > 0) {
    segments.push(`${counts.early} early`);
  }
  return segments.join(", ");
}
