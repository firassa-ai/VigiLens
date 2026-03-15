export interface FirstLoadDemoEntrypointProps {
  drugLabel: string;
  loading: boolean;
  starting: boolean;
  canStart: boolean;
  nextQuarter: string | null;
  onStart: () => Promise<void>;
}

function prettyQuarter(value: string | null): string {
  if (!value) {
    return "-";
  }
  const match = /^(\d{4})-Q([1-4])$/.exec(value);
  if (!match) {
    return value;
  }
  return `Q${match[2]} ${match[1]}`;
}

const VALUE_PROPS = [
  {
    icon: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="10" cy="10" r="7" />
        <polyline points="10,6 10,10 13,12" />
      </svg>
    ),
    title: "Temporal Reasoning",
    desc: "Same question, different answer as new evidence arrives.",
  },
  {
    icon: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 10h12" />
        <path d="M4 6h8" />
        <path d="M4 14h10" />
        <circle cx="16" cy="14" r="2" fill="currentColor" opacity="0.4" />
      </svg>
    ),
    title: "Retroactive Reinterpretation",
    desc: "Old reports gain new meaning when later patterns emerge.",
  },
  {
    icon: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M5 9l3 3 5-6" />
        <circle cx="10" cy="10" r="7" />
      </svg>
    ),
    title: "Receipts + Proof",
    desc: "Semaglutide validates receipts while minoxidil shows proof-backed generalization.",
  },
  {
    icon: (
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 2L4 7v10l8 5 8-5V7l-8-5z" />
        <circle cx="12" cy="12" r="2.5" fill="currentColor" opacity="0.3" />
      </svg>
    ),
    title: "Memory-Native Architecture",
    desc: "Four memory types power understanding databases cannot provide.",
  },
];

const MEMORY_STAGES = [
  { label: "EventLog", color: "#d6a06e", desc: "Timestamped reports" },
  { label: "Episodic", color: "#8b5cf6", desc: "Period narratives" },
  { label: "Profile", color: "#06b6d4", desc: "Evolving view" },
  { label: "Foresight", color: "#22c55e", desc: "Predictions" },
];

export function FirstLoadDemoEntrypoint({
  drugLabel,
  loading,
  starting,
  canStart,
  nextQuarter,
  onStart,
}: FirstLoadDemoEntrypointProps) {
  const busy = starting;
  const buttonDisabled = busy || !canStart;

  return (
    <section className="mb-5 overflow-hidden rounded-2xl border border-[var(--accent-border)] bg-[linear-gradient(145deg,rgba(212,149,106,0.12),rgba(31,31,37,0.96))] shadow-[0_12px_36px_rgba(0,0,0,0.28)]">
      <div className="relative p-8 lg:p-10">
        <div className="pointer-events-none absolute inset-0 -z-0">
          <div className="absolute -top-20 -right-20 h-80 w-80 rounded-full bg-[rgba(212,149,106,0.08)] blur-[80px]" />
          <div className="absolute -bottom-10 -left-20 h-60 w-60 rounded-full bg-[rgba(139,92,246,0.06)] blur-[60px]" />
        </div>

        <div className="relative z-10 grid gap-8 lg:grid-cols-[1fr_auto]">
          <div className="space-y-5">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[var(--accent)]">
                Pharmacovigilance Intelligence
              </p>
              <h2 className="mt-3 font-display text-3xl font-semibold tracking-tight text-[var(--text-primary)] lg:text-4xl">
                Prepare the Two-Drug Demo
              </h2>
              <p className="mt-3 max-w-2xl text-sm leading-relaxed text-[var(--text-secondary)]">
                Prepare the built-in competition demo from the{" "}
                <span className="font-semibold text-[var(--text-primary)]">{drugLabel}</span> workspace.
                Semaglutide loads to the 2018-Q4 baseline so the guided receipt reveal stays intact.
                Minoxidil loads fully through 2023-Q4 so the proof-backed generalization casefile is ready
                immediately.
              </p>
            </div>

            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {VALUE_PROPS.map((prop) => (
                <div
                  key={prop.title}
                  className="rounded-xl border border-white/[0.06] bg-white/[0.02] px-3 py-3 transition hover:border-white/[0.1] hover:bg-white/[0.04]"
                >
                  <div className="mb-2 text-[var(--accent)]">{prop.icon}</div>
                  <p className="text-[11px] font-semibold text-[var(--text-primary)]">{prop.title}</p>
                  <p className="mt-0.5 text-[10px] leading-snug text-[var(--text-tertiary)]">{prop.desc}</p>
                </div>
              ))}
            </div>

            <div className="flex flex-wrap items-center gap-3 pt-1">
              <button
                type="button"
                onClick={() => void onStart()}
                disabled={buttonDisabled}
                className="group inline-flex items-center gap-2 rounded-xl bg-[var(--accent)] px-5 py-3 text-sm font-semibold text-[var(--bg-root)] shadow-[0_4px_16px_rgba(214,160,110,0.25)] transition-all hover:bg-[var(--accent-hover)] hover:shadow-[0_6px_24px_rgba(214,160,110,0.35)] disabled:cursor-not-allowed disabled:opacity-45"
              >
                {starting ? "Preparing reveal..." : loading ? "Loading demo status..." : "Prepare the Demo"}
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none" className="transition-transform group-hover:translate-x-0.5">
                  <path d="M3 8h10M9 4l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
              <div className="flex items-center gap-2 text-xs text-[var(--text-tertiary)]">
                <span className="rounded-md bg-white/[0.06] px-2 py-1">Next: {prettyQuarter(nextQuarter)}</span>
                <span className="rounded-md bg-white/[0.06] px-2 py-1">Reveal at 2023-Q3</span>
                <span className="rounded-md bg-white/[0.06] px-2 py-1">Minoxidil ready at 2023-Q4</span>
              </div>
            </div>
            {!canStart && !busy ? (
              <p className="text-xs text-[var(--text-tertiary)]">
                No additional quarters are available to process for this drug.
              </p>
            ) : null}
          </div>

          <div className="hidden lg:block">
            <div className="w-48 rounded-xl border border-white/[0.06] bg-white/[0.02] p-4">
              <p className="mb-3 text-center text-[10px] font-semibold uppercase tracking-[0.2em] text-[var(--text-tertiary)]">
                Memory Pipeline
              </p>
              <div className="space-y-2">
                {MEMORY_STAGES.map((stage, idx) => (
                  <div key={stage.label} className="flex items-center gap-2">
                    <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg" style={{ background: `color-mix(in srgb, ${stage.color} 15%, transparent)` }}>
                      <span className="text-[10px] font-bold" style={{ color: stage.color }}>{idx + 1}</span>
                    </div>
                    <div>
                      <p className="text-[11px] font-semibold text-[var(--text-primary)]">{stage.label}</p>
                      <p className="text-[9px] text-[var(--text-tertiary)]">{stage.desc}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
