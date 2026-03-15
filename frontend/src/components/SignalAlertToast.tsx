import type { SignalPoint } from "../types/shared";

export interface SignalAlert {
  id: string;
  kind?: "signal" | "reinterpretation";
  headline?: string;
  adverseEvent: string;
  quarter: string;
  ror: number | null;
  ciLower: number | null;
  ciUpper: number | null;
  cumulativeCount: number;
}

export interface SignalAlertToastProps {
  toasts: SignalAlert[];
}

function fmt(value: number | null): string {
  if (value === null || Number.isNaN(value)) {
    return "-";
  }
  return value.toFixed(2);
}

export function detectNewSignals(previous: SignalPoint[], current: SignalPoint[]): SignalAlert[] {
  const previousMap = new Map(previous.map((row) => [row.adverse_event, row]));
  return current
    .filter((row) => {
      const prev = previousMap.get(row.adverse_event);
      return row.signal_detected && (!prev || !prev.signal_detected);
    })
    .map((row) => ({
      id: `${row.quarter}:${row.adverse_event}`,
      kind: "signal" as const,
      adverseEvent: row.adverse_event,
      quarter: row.quarter,
      ror: row.ror,
      ciLower: row.ror_ci_lower,
      ciUpper: row.ror_ci_upper,
      cumulativeCount: row.cumulative_count,
    }));
}

export function SignalAlertToast({ toasts }: SignalAlertToastProps) {
  if (toasts.length === 0) {
    return null;
  }

  return (
    <div className="pointer-events-none fixed right-5 top-20 z-40 flex w-[280px] flex-col gap-2">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className="animate-slide-in-right rounded-lg border border-red-500/20 bg-[var(--bg-root)]/95 p-3 text-xs shadow-2xl backdrop-blur-sm"
        >
          <div className="flex items-center gap-2">
            <span className="h-1.5 w-1.5 rounded-full bg-red-400 shadow-[0_0_6px_rgba(239,68,68,0.5)]" />
            <p className="font-medium text-red-300">
              {toast.kind === "reinterpretation"
                ? "VigiLens Agent: MEMORY REVISION"
                : "VigiLens Agent: New safety signal identified"}
            </p>
          </div>
          <p className="mt-1 text-[var(--text-secondary)]">
            {toast.kind === "reinterpretation"
              ? `I've re-evaluated prior reports and updated the safety profile around ${toast.adverseEvent}.`
              : `${toast.adverseEvent} shows disproportionate reporting (ROR ${fmt(toast.ror)}). Initiating historical memory scan.`}
          </p>
          {toast.kind !== "reinterpretation" ? (
            <p className="mt-1 font-mono text-[var(--text-secondary)]">
              CI {fmt(toast.ciLower)}&ndash;{fmt(toast.ciUpper)}
            </p>
          ) : null}
          <p className="text-[var(--text-tertiary)]">
            Quarter: {toast.quarter} &middot; {toast.cumulativeCount} cumulative reports
          </p>
        </div>
      ))}
    </div>
  );
}
