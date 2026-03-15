type DemoStage = "baseline" | "reveal" | "validation" | "analyst";

export interface DemoModeButtonProps {
  stage: DemoStage;
  running: boolean;
  fastDemoReady?: boolean;
  onRun: () => Promise<void>;
  onFastDemo?: () => Promise<void>;
}

function primaryLabel(stage: DemoStage, running: boolean, fastDemoReady: boolean): string {
  if (running) {
    return "Stop Demo";
  }
  if (stage === "reveal") {
    return "Show FDA receipt";
  }
  if (stage === "validation" || stage === "analyst") {
    return "Replay Demo";
  }
  if (fastDemoReady) {
    return "Reveal reinterpretation";
  }
  return "Run Demo";
}

export function DemoModeButton({
  stage,
  running,
  fastDemoReady = false,
  onRun,
  onFastDemo,
}: DemoModeButtonProps) {
  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={() => void onRun()}
        className="rounded-lg bg-[var(--accent)] px-3 py-1.5 text-xs font-semibold text-[var(--bg-root)] transition hover:bg-[var(--accent-hover)]"
      >
        {primaryLabel(stage, running, fastDemoReady)}
      </button>
      {onFastDemo ? (
        <button
          type="button"
          disabled={running}
          onClick={() => void onFastDemo()}
          className="rounded-lg border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs font-semibold text-[var(--text-secondary)] transition hover:bg-white/[0.08] hover:text-[var(--text-primary)] disabled:cursor-not-allowed disabled:opacity-45"
        >
          Fast Demo
        </button>
      ) : null}
    </div>
  );
}
