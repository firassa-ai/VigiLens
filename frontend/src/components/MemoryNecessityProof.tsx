import { buildEventLogMemoryId, buildForesightMemoryId } from "../lib/memoryProvenance";
import type { FAERSReport, ScorecardEntry } from "../types/shared";

export interface MemoryNecessityProofProps {
  activeQuarter: string | null;
  drugId: string;
  evidenceReport: FAERSReport | null;
  episodicMemoryId: string | null;
  episodicSummary: string | null;
  profileMemoryId: string | null;
  profileSummary: string | null;
  foresightEntry: ScorecardEntry | null;
  showMemorySources?: boolean;
  onOpenEvidence?: (reportId: string) => void;
  onOpenEventLogMemory?: (memoryId: string, report: FAERSReport) => void;
  onOpenMemory?: (memoryId: string) => void;
  onOpenForesightMemory?: (entry: ScorecardEntry, memoryId: string) => void;
}

function shorten(text: string | null | undefined, fallback: string): string {
  const cleaned = (text ?? "").trim();
  if (!cleaned) {
    return fallback;
  }
  return cleaned.length > 84 ? `${cleaned.slice(0, 81).trimEnd()}...` : cleaned;
}

export function MemoryNecessityProof({
  activeQuarter,
  drugId,
  evidenceReport,
  episodicMemoryId,
  episodicSummary,
  profileMemoryId,
  profileSummary,
  foresightEntry,
  showMemorySources = false,
  onOpenEvidence,
  onOpenEventLogMemory,
  onOpenMemory,
  onOpenForesightMemory,
}: MemoryNecessityProofProps) {
  const eventLogMemoryId =
    evidenceReport?.eventlog_memory_id ??
    (evidenceReport ? buildEventLogMemoryId(drugId, evidenceReport.safetyreportid) : null);
  const foresightMemoryId =
    foresightEntry
      ? buildForesightMemoryId(foresightEntry.prediction.drug_id, foresightEntry.prediction.created_at_quarter)
      : null;

  const nodes = [
    {
      key: "eventlog",
      label: "EventLog",
      summary: evidenceReport
        ? `Report ${evidenceReport.safetyreportid}: ${evidenceReport.reactions.slice(0, 2).join(", ") || "report evidence"}`
        : "Select a report to inspect the original patient-level evidence.",
      onOpen: evidenceReport ? () => onOpenEvidence?.(evidenceReport.safetyreportid) : undefined,
      accent: "border-[rgba(190,65,55,0.28)] bg-[rgba(190,65,55,0.08)] text-[var(--danger-accent)]",
      memoryId: showMemorySources && eventLogMemoryId && evidenceReport ? eventLogMemoryId : null,
      onOpenMemory:
        showMemorySources && eventLogMemoryId && evidenceReport
          ? () => onOpenEventLogMemory?.(eventLogMemoryId, evidenceReport)
          : undefined,
    },
    {
      key: "episodic",
      label: "Episodic",
      summary: episodicMemoryId
        ? shorten(episodicSummary, "Quarter narrative available.")
        : "Quarter memory will appear once the case has enough context.",
      onOpen: episodicMemoryId ? () => onOpenMemory?.(episodicMemoryId) : undefined,
      accent: "border-white/10 bg-white/[0.03] text-[var(--text-primary)]",
      memoryId: showMemorySources ? episodicMemoryId : null,
      onOpenMemory: episodicMemoryId ? () => onOpenMemory?.(episodicMemoryId) : undefined,
    },
    {
      key: "profile",
      label: "Profile",
      summary: profileMemoryId
        ? shorten(profileSummary, "Profile memory available.")
        : "Profile memory will appear once the current assessment updates.",
      onOpen: profileMemoryId ? () => onOpenMemory?.(profileMemoryId) : undefined,
      accent: "border-[var(--accent-border)] bg-[var(--accent-dim)] text-[var(--accent)]",
      memoryId: showMemorySources ? profileMemoryId : null,
      onOpenMemory: profileMemoryId ? () => onOpenMemory?.(profileMemoryId) : undefined,
    },
    {
      key: "foresight",
      label: "Foresight",
      summary: foresightEntry
        ? `${foresightEntry.prediction.adverse_event} -> ${foresightEntry.result.toUpperCase()}`
        : "The receipt appears after the reveal progresses into the validation quarter.",
      onOpen:
        foresightEntry && foresightMemoryId
          ? () => onOpenForesightMemory?.(foresightEntry, foresightMemoryId)
          : undefined,
      accent: "border-[rgba(102,153,120,0.28)] bg-[rgba(90,142,111,0.08)] text-[#a8d1b0]",
      memoryId: showMemorySources ? foresightMemoryId : null,
      onOpenMemory:
        foresightEntry && foresightMemoryId
          ? () => onOpenForesightMemory?.(foresightEntry, foresightMemoryId)
          : undefined,
    },
  ] as const;

  return (
    <section className="rounded-[1.3rem] border border-white/10 bg-black/15 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-[var(--text-tertiary)]">
            Proof Chain
          </p>
          <p className="mt-1 text-sm leading-relaxed text-[var(--text-secondary)]">
            Click the chain from original report to memory-backed reinterpretation to FDA receipt.
          </p>
        </div>
        <span className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 font-mono text-[11px] text-[var(--text-secondary)]">
          {activeQuarter ?? "-"}
        </span>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-4">
        {nodes.map((node, index) => (
          <article key={node.key} className={`rounded-[1.15rem] border p-3 ${node.accent}`}>
            <div className="flex items-center gap-2">
              <span className="flex h-6 w-6 items-center justify-center rounded-full border border-current/20 text-[10px] font-semibold">
                {index + 1}
              </span>
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em]">{node.label}</p>
            </div>
            <p className="mt-2 min-h-[54px] text-sm leading-relaxed">{node.summary}</p>
            <button
              type="button"
              disabled={!node.onOpen}
              onClick={() => node.onOpen?.()}
              className="mt-3 rounded-full border border-current/20 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.16em] transition hover:bg-black/10 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Open
            </button>
            {node.memoryId && node.onOpenMemory ? (
              <button
                type="button"
                onClick={() => node.onOpenMemory?.()}
                className="mt-2 block rounded-full border border-current/20 px-3 py-1 font-mono text-[11px] transition hover:bg-black/10"
              >
                {node.memoryId}
              </button>
            ) : null}
          </article>
        ))}
      </div>
    </section>
  );
}
