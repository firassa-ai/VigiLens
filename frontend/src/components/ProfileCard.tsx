import type { DrugProfile } from "../types/shared";

export interface ProfileCardProps {
  profile: DrugProfile | null;
  loading: boolean;
  totalReportsAnalyzed?: number;
  quartersAnalyzed?: number;
  showMemorySources?: boolean;
  memoryUpdatedQuarter?: string | null;
  memoryId?: string | null;
  onOpenMemory?: () => void;
}

const riskDot: Record<string, string> = {
  low: "bg-emerald-400",
  moderate: "bg-yellow-400",
  elevated: "bg-orange-400",
  high: "bg-red-400",
};

const riskText: Record<string, string> = {
  low: "text-emerald-300",
  moderate: "text-yellow-300",
  elevated: "text-orange-300",
  high: "text-red-300",
};

export function ProfileCard({
  profile,
  loading,
  totalReportsAnalyzed = 0,
  quartersAnalyzed = 0,
  showMemorySources = false,
  memoryUpdatedQuarter = null,
  memoryId = null,
  onOpenMemory,
}: ProfileCardProps) {
  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-panel)] p-4">
      <h3 className="mb-3 text-xs font-medium tracking-wide text-[var(--text-tertiary)]">
        Agent&apos;s Drug Assessment
      </h3>
      {loading ? <div className="h-24 animate-pulse rounded-lg bg-[var(--bg-card)]" /> : null}
      {!loading && profile ? (
        <>
          <div className="rounded-lg bg-[var(--bg-card)] p-3">
            <div className="flex items-center gap-2">
              <span className={`h-2.5 w-2.5 rounded-full ${riskDot[profile.risk_level] ?? riskDot.moderate}`} />
              <span className={`text-sm font-semibold tracking-wide ${riskText[profile.risk_level] ?? riskText.moderate}`}>
                {profile.risk_level.toUpperCase()} RISK
              </span>
            </div>
            <p className="mt-2 text-xs leading-relaxed text-[var(--text-secondary)]">
              {profile.current_assessment}
            </p>
          </div>

          <div className="mt-3 rounded-lg bg-[var(--bg-card)] p-3">
            <p className="text-xs text-[var(--text-secondary)]">
              <span className="font-semibold text-[var(--text-primary)]">{profile.known_signals.length}</span> confirmed safety signals
            </p>
            <p className="mt-1 text-xs text-[var(--text-secondary)]">
              <span className="font-semibold text-[var(--text-primary)]">{profile.investigating_signals.length}</span> signals under investigation
            </p>
            <p className="mt-1 text-xs text-[var(--text-secondary)]">
              <span className="font-semibold text-[var(--text-primary)]">{totalReportsAnalyzed.toLocaleString("en-US")}</span> reports analyzed across {quartersAnalyzed} quarters
            </p>
          </div>

          <div className="mt-4">
            <p className="text-xs font-medium text-[var(--text-tertiary)]">Known signals</p>
            <div className="mt-1.5 flex flex-wrap gap-1">
              {profile.known_signals.map((value) => (
                <span
                  key={value}
                  className="rounded-md bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-300"
                >
                  {value}
                </span>
              ))}
            </div>
          </div>

          <div className="mt-3">
            <p className="text-xs font-medium text-[var(--text-tertiary)]">Investigating</p>
            <div className="mt-1.5 flex flex-wrap gap-1">
              {profile.investigating_signals.length > 0 ? (
                profile.investigating_signals.map((value) => (
                  <span
                    key={value}
                    className="rounded-md bg-[var(--accent-dim)] px-2 py-0.5 text-xs text-[var(--accent)]"
                  >
                    {value}
                  </span>
                ))
              ) : (
                <span className="rounded-md bg-white/[0.04] px-2 py-0.5 text-xs text-[var(--text-secondary)]">
                  None this quarter
                </span>
              )}
            </div>
          </div>

          <p className="mt-3 text-[11px] leading-relaxed text-[var(--text-tertiary)]">
            Based on FDA FAERS spontaneous reports. Reports are unverified and cannot establish causation.
          </p>

          {showMemorySources ? (
            <div className="mt-3 rounded-md bg-[var(--bg-card)] px-2.5 py-1.5 text-xs text-[var(--text-secondary)]">
              <p>Profile stored in EverMemOS | Last updated: {memoryUpdatedQuarter ?? "-"}</p>
              {memoryId ? (
                <button
                  type="button"
                  onClick={onOpenMemory}
                  className="mt-1 rounded bg-white/[0.04] px-1.5 py-0.5 font-mono text-[11px] text-[var(--text-tertiary)] transition hover:bg-white/[0.08] hover:text-[var(--text-primary)]"
                >
                  {memoryId}
                </button>
              ) : null}
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
