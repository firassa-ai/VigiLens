import type { ForesightMemoryStatus } from "../types/shared";

type MemoryStatusTone = "ok" | "warning" | "idle";

export interface MemoryProvenanceProps {
  enabled: boolean;
  onToggle: () => void;
  memoryStatusLabel: string;
  memoryStatusTone?: MemoryStatusTone;
  foresightStatus?: ForesightMemoryStatus | null;
}

function toneClass(tone: MemoryStatusTone): string {
  if (tone === "ok") {
    return "border-emerald-500/20 bg-emerald-500/10 text-emerald-200";
  }
  if (tone === "warning") {
    return "border-amber-500/20 bg-amber-500/10 text-amber-200";
  }
  return "border-white/10 bg-white/[0.04] text-[var(--text-secondary)]";
}

function summaryLabel(foresightStatus: ForesightMemoryStatus | null): string {
  if (!foresightStatus) {
    return "Memory receipts and platform diagnostics are hidden until you open provenance mode.";
  }
  if (foresightStatus.status === "warning") {
    return "Diagnostics are available for Q&A. The main casefile stays neutral even when memory writes partially degrade.";
  }
  return "Diagnostics are available for Q&A. Open provenance mode to inspect memory IDs and write status.";
}

export function MemoryProvenance({
  enabled,
  onToggle,
  memoryStatusLabel,
  memoryStatusTone = "idle",
  foresightStatus = null,
}: MemoryProvenanceProps) {
  return (
    <section className="rounded-xl border border-[var(--border)] bg-[var(--bg-panel)] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-medium tracking-wide text-[var(--text-tertiary)]">Memory Diagnostics</p>
          <p className="mt-1 text-sm leading-relaxed text-[var(--text-secondary)]">{summaryLabel(foresightStatus)}</p>
        </div>
        <div className={`rounded-full border px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] ${toneClass(memoryStatusTone)}`}>
          {memoryStatusLabel}
        </div>
      </div>

      <button
        type="button"
        onClick={onToggle}
        className="mt-3 rounded-lg bg-white/[0.04] px-3 py-2 text-xs font-semibold text-[var(--text-secondary)] transition hover:bg-white/[0.08] hover:text-[var(--text-primary)]"
      >
        {enabled ? "Hide provenance + diagnostics" : "Open provenance + diagnostics"}
      </button>

      {enabled && foresightStatus ? (
        <div className="mt-3 rounded-lg border border-white/10 bg-[var(--bg-card)] p-3 text-sm text-[var(--text-secondary)]">
          <p className="font-medium text-[var(--text-primary)]">{foresightStatus.message}</p>
          <p className="mt-1 text-xs text-[var(--text-tertiary)]">
            Writes: {foresightStatus.successful_writes}/{foresightStatus.attempted_writes}
            {foresightStatus.failed_writes > 0 ? ` | Failed: ${foresightStatus.failed_writes}` : ""}
            {foresightStatus.last_attempted_quarter
              ? ` | Last quarter: ${foresightStatus.last_attempted_quarter}`
              : ""}
          </p>
        </div>
      ) : null}
    </section>
  );
}
