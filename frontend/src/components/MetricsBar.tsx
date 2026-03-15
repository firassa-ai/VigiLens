import { useEffect, useRef, useState } from "react";

interface MetricCardProps {
  label: string;
  value: number;
  icon: React.ReactNode;
  suffix?: string | null;
  accentColor?: string;
}

function useAnimatedCount(target: number, durationMs = 600): number {
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
      const current = Math.round(from + delta * eased);
      setDisplay(current);
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

function MetricCard({ label, value, icon, suffix, accentColor = "var(--accent)" }: MetricCardProps) {
  const animated = useAnimatedCount(value);

  return (
    <div className="group relative flex items-center gap-3 rounded-xl border border-white/[0.06] bg-[var(--bg-panel)] px-4 py-3 transition-all duration-200 hover:border-white/[0.1] hover:bg-[var(--bg-card)]">
      <div
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg transition-colors"
        style={{ background: `color-mix(in srgb, ${accentColor} 12%, transparent)`, color: accentColor }}
      >
        {icon}
      </div>
      <div className="min-w-0">
        <p className="text-[11px] font-medium uppercase tracking-[0.12em] text-[var(--text-tertiary)]">{label}</p>
        <p className="mt-0.5 font-display text-xl font-semibold tabular-nums text-[var(--text-primary)]">
          {animated.toLocaleString("en-US")}
          {suffix ? <span className="ml-1 text-sm font-normal text-[var(--text-secondary)]">{suffix}</span> : null}
        </p>
      </div>
    </div>
  );
}

export interface MetricsBarProps {
  totalReports: number;
  activeSignals: number;
  beliefsTracked: number;
  predictionsValidated: number;
  predictionsTotal: number;
  quartersLoaded: number;
  predictionLabel?: string;
  predictionValue?: number;
  predictionSuffix?: string | null;
}

export function MetricsBar({
  totalReports,
  activeSignals,
  beliefsTracked,
  predictionsValidated,
  predictionsTotal,
  quartersLoaded,
  predictionLabel = "Predictions",
  predictionValue = predictionsValidated,
  predictionSuffix,
}: MetricsBarProps) {
  const resolvedPredictionSuffix = predictionSuffix === undefined ? `/ ${predictionsTotal}` : predictionSuffix;

  return (
    <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5 animate-fade-up" style={{ animationDelay: "80ms" }}>
      <MetricCard
        label="Reports Analyzed"
        value={totalReports}
        accentColor="var(--accent)"
        icon={
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M5 2h8l3 3v10a1 1 0 01-1 1H5a1 1 0 01-1-1V3a1 1 0 011-1z" />
            <path d="M13 2v3h3" />
          </svg>
        }
      />
      <MetricCard
        label="Active Signals"
        value={activeSignals}
        accentColor="#ef4444"
        icon={
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M9 2v6" />
            <circle cx="9" cy="13" r="1" fill="currentColor" />
            <path d="M3.5 5.5a8 8 0 0111 0" />
            <path d="M5.5 8a5 5 0 017 0" />
          </svg>
        }
      />
      <MetricCard
        label="Beliefs Tracked"
        value={beliefsTracked}
        accentColor="#8b5cf6"
        icon={
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="9" cy="9" r="6" />
            <path d="M9 6v3l2 1" />
          </svg>
        }
      />
      <MetricCard
        label={predictionLabel}
        value={predictionValue}
        suffix={resolvedPredictionSuffix}
        accentColor="#22c55e"
        icon={
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M5 9l3 3 5-6" />
            <circle cx="9" cy="9" r="7" />
          </svg>
        }
      />
      <MetricCard
        label="Quarters Loaded"
        value={quartersLoaded}
        accentColor="#06b6d4"
        icon={
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="4" width="12" height="10" rx="1" />
            <path d="M3 8h12" />
            <path d="M7 4v10" />
          </svg>
        }
      />
    </div>
  );
}
