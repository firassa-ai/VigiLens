import type { BeliefDiff, ScorecardEntry } from "../types/shared";

type DemoStage = "baseline" | "reveal" | "validation" | "analyst";
type MemoryStatusTone = "ok" | "warning" | "idle";

export interface StoryHeaderProps {
  viewingQuarter: string | null;
  totalReportsLoaded: number;
  demoStage: DemoStage;
  memoryStatusLabel: string;
  memoryStatusTone?: MemoryStatusTone;
  beliefDiff?: BeliefDiff | null;
  primaryReceipt?: ScorecardEntry | null;
  secondaryReceiptCount?: number;
}

function toneClass(tone: MemoryStatusTone): string {
  if (tone === "ok") {
    return "border-emerald-500/25 bg-emerald-500/10 text-emerald-200";
  }
  if (tone === "warning") {
    return "border-amber-500/25 bg-amber-500/10 text-amber-200";
  }
  return "border-white/10 bg-white/[0.04] text-[var(--text-secondary)]";
}

function formatNumber(value: number): string {
  return value.toLocaleString("en-US");
}

function stageCopy(params: {
  demoStage: DemoStage;
  viewingQuarter: string | null;
  beliefDiff: BeliefDiff | null;
  primaryReceipt: ScorecardEntry | null;
  secondaryReceiptCount: number;
}): { eyebrow: string; headline: string; summary: string } {
  const { demoStage, viewingQuarter, beliefDiff, primaryReceipt, secondaryReceiptCount } = params;
  const reinterpretationCount = beliefDiff?.reinterpreted_report_ids.length ?? 0;

  if (demoStage === "reveal") {
    return {
      eyebrow: "Reveal Quarter",
      headline: "Earlier reports are being reclassified as precursor evidence.",
      summary:
        reinterpretationCount > 0
          ? `${viewingQuarter ?? "2023-Q3"} is the quarter where the case changes. ${reinterpretationCount} earlier report${
              reinterpretationCount === 1 ? "" : "s"
            } move from routine GI noise to meaningful precursor evidence.`
          : `${viewingQuarter ?? "2023-Q3"} is the reveal. The signal pattern has changed enough for VigiLens to revisit earlier GI reports with new context.`,
    };
  }

  if (demoStage === "validation") {
    const title = primaryReceipt?.actual_fda_action?.title ?? "later FDA action";
    return {
      eyebrow: "FDA Receipt",
      headline: "The ileus forecast now has a concrete FDA receipt.",
      summary:
        secondaryReceiptCount > 0
          ? `${viewingQuarter ?? "2023-Q4"} surfaces the primary ileus receipt first, while ${secondaryReceiptCount} additional tracked validation${
              secondaryReceiptCount === 1 ? "" : "s"
            } remain available in the scorecard. Primary receipt: ${title}.`
          : `${viewingQuarter ?? "2023-Q4"} surfaces the primary ileus receipt first. Primary receipt: ${title}.`,
    };
  }

  if (demoStage === "analyst") {
    return {
      eyebrow: "Analyst Workspace",
      headline: "The full investigative workspace is open.",
      summary:
        "Use time travel, queries, diagnostics, and multi-drug tools for Q&A without interrupting the main casefile story.",
    };
  }

  return {
    eyebrow: "Baseline Casefile",
    headline: "Semaglutide starts as familiar GI noise, not a crisis.",
    summary:
      "This baseline is intentionally quiet. Run the demo to land on the 2023-Q3 reinterpretation quarter, then advance once more for the FDA receipt.",
  };
}

export function StoryHeader({
  viewingQuarter,
  totalReportsLoaded,
  demoStage,
  memoryStatusLabel,
  memoryStatusTone = "idle",
  beliefDiff = null,
  primaryReceipt = null,
  secondaryReceiptCount = 0,
}: StoryHeaderProps) {
  const copy = stageCopy({
    demoStage,
    viewingQuarter,
    beliefDiff,
    primaryReceipt,
    secondaryReceiptCount,
  });
  const reinterpretationCount = beliefDiff?.reinterpreted_report_ids.length ?? 0;

  return (
    <section className="mb-5 animate-fade-up">
      <div className="rounded-[1.6rem] border border-[var(--border)] bg-[linear-gradient(140deg,rgba(18,18,22,0.96),rgba(42,31,22,0.9))] p-5 shadow-[0_18px_50px_rgba(0,0,0,0.24)]">
        <div className="flex flex-wrap items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em]">
          <span className="rounded-full border border-[var(--accent-border)] bg-[var(--accent-dim)] px-3 py-1 text-[var(--accent)]">
            {copy.eyebrow}
          </span>
          <span className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-[var(--text-secondary)]">
            Viewing {viewingQuarter ?? "-"}
          </span>
          <span className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-[var(--text-secondary)]">
            {formatNumber(totalReportsLoaded)} reports
          </span>
          <span className={`rounded-full border px-3 py-1 ${toneClass(memoryStatusTone)}`}>
            {memoryStatusLabel}
          </span>
          {demoStage === "reveal" && reinterpretationCount > 0 ? (
            <span className="rounded-full border border-[rgba(190,65,55,0.28)] bg-[rgba(190,65,55,0.1)] px-3 py-1 text-[var(--danger-accent)]">
              {reinterpretationCount} reinterpreted report{reinterpretationCount === 1 ? "" : "s"}
            </span>
          ) : null}
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(280px,0.8fr)]">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-[var(--text-tertiary)]">
              The report didn&apos;t change. The meaning changed.
            </p>
            <h2 className="mt-2 font-display text-[clamp(1.8rem,4vw,3rem)] leading-[0.98] text-[var(--text-primary)]">
              {copy.headline}
            </h2>
            <p className="mt-3 max-w-4xl text-sm leading-relaxed text-[var(--text-secondary)]">{copy.summary}</p>
          </div>

          <div className="rounded-[1.35rem] border border-white/10 bg-black/20 p-4">
            <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-[var(--text-tertiary)]">
              Casefile Focus
            </p>
            <p className="mt-2 text-sm leading-relaxed text-[var(--text-secondary)]">
              {demoStage === "validation"
                ? "Lead with the ileus receipt, then open the evidence report, episodic memory, and foresight record if someone asks how the chain was built."
                : demoStage === "reveal"
                  ? "Lead with the reinterpretation moment, then click the linked report and episodic memory before moving to the receipt."
                  : demoStage === "analyst"
                    ? "Use this mode for breadth: time travel, provenance, memory IDs, and ad-hoc questions."
                    : "The first act is calm by design. The strongest story cue arrives when the case pauses at 2023-Q3."}
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
