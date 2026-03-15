import { type ReactNode, useEffect, useRef, useState } from "react";

import type { BeliefDiff } from "../types/shared";

export interface BeliefRevisionHeroProps {
  activeQuarter: string | null;
  diff: BeliefDiff | null;
  drugLabel?: string;
  loading?: boolean;
  highlight?: boolean;
  proofChain?: ReactNode;
  memoryReceiptIds?: string[];
  onOpenEvidence?: (reportId: string) => void;
  onOpenMemory?: (memoryId: string) => void;
}

function firstMeaningfulLine(text: string): string {
  const line = text
    .split("\n")
    .map((value) => value.trim())
    .find((value) => value.length > 0);
  return line ?? "No belief snapshot available.";
}

function signedDelta(value: number): string {
  if (value > 0) {
    return `+${value}`;
  }
  return String(value);
}

function useCountUp(target: number, durationMs = 700): number {
  const [display, setDisplay] = useState(0);
  const prevRef = useRef(0);
  const frameRef = useRef(0);

  useEffect(() => {
    const from = prevRef.current;
    const delta = target - from;
    if (delta === 0) return;
    const start = performance.now();

    function step(now: number) {
      const elapsed = now - start;
      const progress = Math.min(elapsed / durationMs, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplay(Math.round(from + delta * eased));
      if (progress < 1) {
        frameRef.current = requestAnimationFrame(step);
      } else {
        prevRef.current = target;
      }
    }

    frameRef.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frameRef.current);
  }, [target, durationMs]);

  return display;
}

export function BeliefRevisionHero({
  activeQuarter,
  diff,
  drugLabel = "the drug",
  loading = false,
  highlight = false,
  proofChain = null,
  memoryReceiptIds = [],
  onOpenEvidence,
  onOpenMemory,
}: BeliefRevisionHeroProps) {
  const animatedDelta = useCountUp(diff?.confidence_delta ?? 0);
  const animatedReinterpret = useCountUp(diff?.reinterpreted_report_ids.length ?? 0);

  if (loading) {
    return <section className="h-[280px] animate-pulse rounded-[1.6rem] bg-[rgba(255,255,255,0.04)]" />;
  }

  if (!diff) {
    return (
      <section className="rounded-[1.6rem] border border-[var(--border)] bg-[var(--bg-panel)] p-6">
        <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-[var(--text-tertiary)]">
          Belief Revision
        </p>
        <h2 className="mt-2 font-display text-2xl text-[var(--text-primary)]">
          Run the case to the quarter where the interpretation changes.
        </h2>
        <p className="mt-3 max-w-3xl text-sm leading-relaxed text-[var(--text-secondary)]">
          The first act stays calm on purpose. When a new safety pattern crosses the threshold, VigiLens compares the
          old belief with the current one and surfaces which earlier reports changed meaning.
        </p>
      </section>
    );
  }

  const beforeSummary = firstMeaningfulLine(diff.before.answer_text);
  const afterSummary = firstMeaningfulLine(diff.after.answer_text);
  const reinterpretationCount = diff.reinterpreted_report_ids.length;
  const memoryIds = memoryReceiptIds.length > 0
    ? memoryReceiptIds.slice(0, 4)
    : diff.after.episodic_ids_used.slice(0, 4);

  return (
    <section
      className={`relative overflow-hidden rounded-[1.6rem] border p-6 transition-all duration-500 ${
        highlight
          ? "border-[rgba(190,65,55,0.45)] bg-[linear-gradient(135deg,rgba(190,65,55,0.12),rgba(20,17,18,0.96))] shadow-[0_20px_90px_rgba(190,65,55,0.2)]"
          : "border-[var(--border)] bg-[var(--bg-panel)]"
      }`}
    >
      {highlight && (
        <div className="pointer-events-none absolute inset-0 -z-0">
          <div className="absolute -top-20 -right-20 h-60 w-60 rounded-full bg-[rgba(190,65,55,0.08)] blur-3xl" />
          <div className="absolute -bottom-10 -left-10 h-40 w-40 rounded-full bg-[rgba(212,149,106,0.06)] blur-3xl" />
        </div>
      )}
      <div className="relative z-10">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-[var(--danger-accent)]">
              Belief Revision
            </p>
            <h2 className="mt-2 font-display text-[clamp(1.9rem,4vw,3.2rem)] leading-[0.96] text-[var(--text-primary)]">
              <span className="font-mono tabular-nums">{reinterpretationCount}</span> report{reinterpretationCount === 1 ? "" : "s"} stayed the same.
              <br />
              <span className={`text-[var(--danger-accent)] ${highlight ? "belief-text-glow" : ""}`}>
                Their meaning didn&rsquo;t.
              </span>
            </h2>
          </div>
          <div className="rounded-2xl border border-[rgba(255,255,255,0.08)] bg-black/20 px-5 py-3 text-right backdrop-blur-sm">
            <p className="text-[10px] uppercase tracking-[0.24em] text-[var(--text-tertiary)]">Trigger quarter</p>
            <p className="mt-1.5 font-mono text-xl font-semibold text-[var(--text-primary)]">
              {activeQuarter ?? diff.triggered_by_quarter}
            </p>
          </div>
        </div>

        <div className="mt-6 grid gap-4 lg:grid-cols-[minmax(0,1fr)_200px_minmax(0,1fr)]">
          <article className="rounded-[1.25rem] border border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.03)] p-5 backdrop-blur-sm">
            <div className="flex items-center gap-2.5">
              <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-[var(--text-tertiary)]">Then</p>
              <span className="rounded-full border border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.05)] px-2 py-0.5 text-[9px] font-medium uppercase tracking-wider text-[var(--text-muted)]">
                Superseded
              </span>
            </div>
            <p className="mt-3 font-display text-lg leading-snug text-[var(--text-muted)] opacity-50">
              {beforeSummary}
            </p>
            <p className="mt-4 text-xs leading-relaxed text-[var(--text-secondary)]">
              Earlier quarters treated these reports as routine background noise within the known {drugLabel} profile.
            </p>
          </article>

          <div className="flex flex-col items-center justify-center rounded-[1.25rem] border border-[rgba(190,65,55,0.3)] bg-[rgba(190,65,55,0.08)] p-5 text-center backdrop-blur-sm">
            <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-[var(--danger-accent)]">Delta</p>
            <p className="mt-3 font-mono text-4xl font-bold tabular-nums text-[var(--text-primary)]">
              {animatedDelta > 0 ? "+" : ""}{animatedDelta}
            </p>
            <p className="mt-1 text-[11px] text-[var(--text-secondary)]">confidence shift</p>
            <div className="mt-4 h-px w-8 bg-white/10" />
            <p className="mt-4 font-mono text-3xl font-bold tabular-nums text-[var(--text-primary)]">{animatedReinterpret}</p>
            <p className="mt-1 text-[11px] text-[var(--text-secondary)]">
              reinterpreted report{reinterpretationCount === 1 ? "" : "s"}
            </p>
          </div>

          <article className="rounded-[1.25rem] border border-[var(--accent-border)] bg-[var(--accent-dim)] p-5 backdrop-blur-sm">
            <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-[var(--accent)]">Now</p>
            <p className="mt-3 font-display text-lg leading-snug text-[var(--text-primary)]">{afterSummary}</p>
            <p className="mt-4 text-xs leading-relaxed text-[var(--text-secondary)]">
              After the new threshold crossing, VigiLens revisits earlier reports and reclassifies them as precursor evidence.
            </p>
          </article>
        </div>
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        <div className="rounded-2xl border border-[rgba(255,255,255,0.08)] bg-black/15 p-4">
          <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-[var(--text-tertiary)]">
            Reinterpreted Reports
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {diff.reinterpreted_report_ids.length > 0 ? (
              diff.reinterpreted_report_ids.slice(0, 8).map((reportId) => (
                <button
                  key={reportId}
                  type="button"
                  onClick={() => onOpenEvidence?.(reportId)}
                  className="rounded-full border border-[rgba(190,65,55,0.36)] bg-[rgba(190,65,55,0.12)] px-3 py-1 font-mono text-[11px] text-[var(--danger-accent)] transition hover:bg-[rgba(190,65,55,0.2)]"
                >
                  {reportId}
                </button>
              ))
            ) : (
              <p className="text-xs text-[var(--text-secondary)]">No report-level reinterpretation IDs were returned for this comparison.</p>
            )}
          </div>
        </div>

        <div className="rounded-2xl border border-[rgba(255,255,255,0.08)] bg-black/15 p-4">
          <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-[var(--text-tertiary)]">
            Memory Receipts
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {memoryIds.length > 0 ? (
              memoryIds.map((memoryId) => (
                <button
                  key={memoryId}
                  type="button"
                  onClick={() => onOpenMemory?.(memoryId)}
                  className="rounded-full border border-[var(--accent-border)] bg-[var(--accent-dim)] px-3 py-1 font-mono text-[11px] text-[var(--accent)] transition hover:bg-[rgba(212,149,106,0.22)]"
                >
                  {memoryId}
                </button>
              ))
            ) : (
              <p className="text-xs text-[var(--text-secondary)]">No episodic memory IDs were attached to this belief diff.</p>
            )}
          </div>
        </div>
      </div>
      {proofChain ? <div className="mt-5">{proofChain}</div> : null}
    </section>
  );
}
