import { useEffect, useState } from "react";

export interface MemoryArchitectureCardProps {
  totalReports: number;
  episodicCount: number;
  profileUpdated: boolean;
  foresightCount: number;
  evermemosOk: boolean;
  onOpenMemoryType?: (type: "EventLog" | "Episodic" | "Profile" | "Foresight") => void;
}

interface NodeProps {
  label: string;
  sublabel: string;
  count: number | string;
  color: string;
  pulse?: boolean;
  onClick?: () => void;
}

function FlowNode({ label, sublabel, count, color, pulse, onClick }: NodeProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="group/node relative flex flex-col items-center gap-1.5 rounded-xl border border-white/[0.06] bg-[var(--bg-card)] px-4 py-3 transition-all duration-200 hover:border-white/[0.12] hover:bg-[var(--bg-elevated)]"
      style={{ minWidth: 100 }}
    >
      {pulse && (
        <span
          className="absolute -top-1 -right-1 h-2.5 w-2.5 rounded-full animate-pulse"
          style={{ background: color, boxShadow: `0 0 8px ${color}` }}
        />
      )}
      <div
        className="flex h-8 w-8 items-center justify-center rounded-lg transition-transform duration-200 group-hover/node:scale-110"
        style={{ background: `color-mix(in srgb, ${color} 15%, transparent)` }}
      >
        <span className="text-xs font-bold" style={{ color }}>{typeof count === "number" ? count : count}</span>
      </div>
      <p className="text-[11px] font-semibold text-[var(--text-primary)]">{label}</p>
      <p className="text-[10px] text-[var(--text-tertiary)]">{sublabel}</p>
    </button>
  );
}

function Arrow({ animated, color }: { animated?: boolean; color: string }) {
  return (
    <div className="flex items-center px-1">
      <svg width="32" height="16" viewBox="0 0 32 16" className="shrink-0">
        <defs>
          <linearGradient id={`arrow-grad-${color.replace("#", "")}`} x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor={color} stopOpacity="0.2" />
            <stop offset="100%" stopColor={color} stopOpacity="0.6" />
          </linearGradient>
        </defs>
        <line
          x1="2" y1="8" x2="24" y2="8"
          stroke={`url(#arrow-grad-${color.replace("#", "")})`}
          strokeWidth="1.5"
          strokeDasharray={animated ? "4 3" : "none"}
          className={animated ? "animate-flow" : ""}
        />
        <polygon
          points="24,4 30,8 24,12"
          fill={color}
          opacity="0.5"
        />
      </svg>
    </div>
  );
}

export function MemoryArchitectureCard({
  totalReports,
  episodicCount,
  profileUpdated,
  foresightCount,
  evermemosOk,
  onOpenMemoryType,
}: MemoryArchitectureCardProps) {
  const [flowPulse, setFlowPulse] = useState(false);

  useEffect(() => {
    if (totalReports > 0) {
      setFlowPulse(true);
      const timer = setTimeout(() => setFlowPulse(false), 2000);
      return () => clearTimeout(timer);
    }
  }, [totalReports]);

  return (
    <div className="rounded-xl border border-white/[0.06] bg-[var(--bg-panel)] p-5">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-[var(--text-tertiary)]">
            Memory Architecture
          </p>
          <p className="mt-1 text-xs text-[var(--text-secondary)]">
            How EverMemOS builds temporal understanding
          </p>
        </div>
        <span
          className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] font-medium ${
            evermemosOk
              ? "bg-emerald-500/10 text-emerald-300 border border-emerald-500/20"
              : "bg-amber-500/10 text-amber-300 border border-amber-500/20"
          }`}
        >
          <span className={`h-1.5 w-1.5 rounded-full ${evermemosOk ? "bg-emerald-400" : "bg-amber-400"}`} />
          {evermemosOk ? "Connected" : "Degraded"}
        </span>
      </div>

      <div className="flex flex-wrap items-center justify-center gap-y-3 overflow-x-auto py-2">
        <FlowNode
          label="FAERS"
          sublabel="Raw reports"
          count={totalReports}
          color="var(--accent)"
          pulse={flowPulse}
        />
        <Arrow animated={flowPulse} color="#d6a06e" />
        <FlowNode
          label="EventLog"
          sublabel="Timestamped"
          count={totalReports}
          color="#d6a06e"
          pulse={flowPulse}
          onClick={() => onOpenMemoryType?.("EventLog")}
        />
        <Arrow animated={flowPulse} color="#8b5cf6" />
        <FlowNode
          label="Episodic"
          sublabel="Narratives"
          count={episodicCount}
          color="#8b5cf6"
          onClick={() => onOpenMemoryType?.("Episodic")}
        />
        <Arrow animated color="#06b6d4" />
        <FlowNode
          label="Profile"
          sublabel="Evolving view"
          count={profileUpdated ? "Active" : "-"}
          color="#06b6d4"
          pulse={profileUpdated}
          onClick={() => onOpenMemoryType?.("Profile")}
        />
        <Arrow animated color="#22c55e" />
        <FlowNode
          label="Foresight"
          sublabel="Predictions"
          count={foresightCount}
          color="#22c55e"
          onClick={() => onOpenMemoryType?.("Foresight")}
        />
      </div>

      <div className="mt-3 rounded-lg bg-white/[0.02] px-3 py-2 text-center text-[11px] leading-relaxed text-[var(--text-tertiary)]">
        Postgres holds the canonical ledger. EverMemOS adds temporal understanding that enables retrospective reinterpretation.
      </div>
    </div>
  );
}
