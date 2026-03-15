import type { FDAAction, ScorecardEntry, ScorecardResult } from "../types/shared";

export function quarterSortValue(quarter: string): number {
  const match = /^(\d{4})-Q([1-4])$/.exec(quarter);
  if (!match) {
    return -1;
  }
  return Number(match[1]) * 10 + Number(match[2]);
}

function quarterEndDate(quarter: string): Date | null {
  const match = /^(\d{4})-Q([1-4])$/.exec(quarter);
  if (!match) {
    return null;
  }
  const year = Number(match[1]);
  const q = Number(match[2]);
  const startMonth = (q - 1) * 3;
  return new Date(Date.UTC(year, startMonth + 3, 0, 23, 59, 59, 999));
}

function parseDate(value: string): Date | null {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }
  return parsed;
}

function actionVisibleAsOf(action: FDAAction | null, asOfEnd: Date | null): boolean {
  if (!action) {
    return false;
  }
  if (!asOfEnd) {
    return true;
  }
  const actionDate = parseDate(action.date);
  if (!actionDate) {
    return true;
  }
  return actionDate <= asOfEnd;
}

function projectResult(
  entry: ScorecardEntry,
  params: { actionVisible: boolean; asOfEnd: Date | null },
): ScorecardResult {
  const { actionVisible, asOfEnd } = params;
  if (!asOfEnd) {
    return entry.result;
  }
  if (actionVisible) {
    return entry.result;
  }
  const predictedEnd = parseDate(entry.prediction.predicted_date_range[1]);
  if (predictedEnd && predictedEnd < asOfEnd) {
    return "missed";
  }
  return "pending";
}

export function projectScorecardAsOf(
  entries: ScorecardEntry[],
  asOfQuarter: string | null,
  loadedThroughQuarter: string | null = null,
): ScorecardEntry[] {
  if (!asOfQuarter) {
    return entries;
  }

  const asOfEnd = quarterEndDate(asOfQuarter);
  return entries
    .filter((entry) => quarterSortValue(entry.prediction.created_at_quarter) <= quarterSortValue(asOfQuarter))
    .map((entry) => {
      const actionVisible = actionVisibleAsOf(entry.actual_fda_action, asOfEnd);
      return {
        ...entry,
        result: projectResult(entry, { actionVisible, asOfEnd }),
        actual_fda_action: actionVisible ? entry.actual_fda_action : null,
      };
    });
}
