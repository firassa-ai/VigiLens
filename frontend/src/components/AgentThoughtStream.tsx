import { useEffect, useMemo, useRef, useState } from "react";

import type { AgentThoughtType } from "../types/shared";

export type AgentRunState = "idle" | "running" | "complete" | "error" | "cancelled";

export interface AgentLogEntry {
  id: string;
  type: AgentThoughtType;
  content: string;
  timestamp: string;
  memoryRefs?: string[];
  metadata?: Record<string, unknown>;
  origin?: "server" | "narrative";
}

export interface AgentThoughtStreamProps {
  entries: AgentLogEntry[];
  runState: AgentRunState;
  showMemorySources: boolean;
  onOpenMemoryRef?: (memoryId: string, entry: AgentLogEntry) => void;
  idleHint?: string;
  compact?: boolean;
}

const typeStyles: Record<AgentThoughtType, { label: string; badge: string; text: string }> = {
  perceive: {
    label: "PERCEIVE",
    badge: "border-blue-400/40 bg-blue-500/12 text-[#60A5FA]",
    text: "text-[#93C5FD]",
  },
  tool: {
    label: "TOOL",
    badge: "border-cyan-400/40 bg-cyan-500/12 text-[#22D3EE]",
    text: "text-cyan-200",
  },
  memory_query: {
    label: "MEMORY_QUERY",
    badge: "border-violet-400/40 bg-violet-500/12 text-[#A78BFA]",
    text: "text-violet-200",
  },
  memory_recall: {
    label: "MEMORY_RECALL",
    badge: "border-violet-400/40 bg-violet-500/12 text-[#A78BFA]",
    text: "text-violet-200",
  },
  reasoning: {
    label: "REASONING",
    badge: "border-amber-300/40 bg-amber-500/10 text-[#FBBF24]",
    text: "text-amber-200",
  },
  reinterpretation: {
    label: "REINTERPRETATION",
    badge: "border-red-300/50 bg-red-500/12 text-[#F87171]",
    text: "text-red-200",
  },
  memory_write: {
    label: "MEMORY_WRITE",
    badge: "border-emerald-300/40 bg-emerald-500/10 text-[#34D399]",
    text: "text-emerald-200",
  },
  foresight: {
    label: "FORESIGHT",
    badge: "border-amber-400/40 bg-amber-500/10 text-[#F59E0B]",
    text: "text-amber-200",
  },
  action: {
    label: "ACTION",
    badge: "border-slate-300/35 bg-slate-400/10 text-slate-200",
    text: "text-slate-200",
  },
};

function toTimeLabel(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) {
    return iso;
  }
  return parsed.toLocaleTimeString("en-US", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZone: "UTC",
  });
}

export function AgentThoughtStream({
  entries,
  runState,
  showMemorySources,
  onOpenMemoryRef,
  idleHint,
  compact = false,
}: AgentThoughtStreamProps) {
  const [reinterpretationPulse, setReinterpretationPulse] = useState(false);
  const lastPulseEntryRef = useRef<string | null>(null);
  const viewportRef = useRef<HTMLDivElement | null>(null);

  const active = runState === "running";
  const statusLabel = runState === "idle" ? "MONITORING" : runState.toUpperCase();
  const latest = entries.at(-1) ?? null;

  useEffect(() => {
    if (!latest || latest.type !== "reinterpretation") {
      return;
    }
    if (lastPulseEntryRef.current === latest.id) {
      return;
    }
    lastPulseEntryRef.current = latest.id;
    setReinterpretationPulse(true);
    const timer = window.setTimeout(() => {
      setReinterpretationPulse(false);
    }, 1500);
    return () => {
      window.clearTimeout(timer);
    };
  }, [latest]);

  useEffect(() => {
    if (!active || !viewportRef.current) {
      return;
    }
    viewportRef.current.scrollTop = viewportRef.current.scrollHeight;
  }, [active, entries]);

  const panelClass = useMemo(() => {
    if (!reinterpretationPulse) {
      return "border-[var(--border)]";
    }
    return "border-red-400/60 shadow-[0_0_0_1px_rgba(248,113,113,0.45),0_0_22px_rgba(248,113,113,0.28)]";
  }, [reinterpretationPulse]);

  const emptyMessage = useMemo(() => {
    if (runState === "idle") {
      return (
        idleHint ??
        "Agent ready. Run the staged demo or open the analyst workspace to inspect live reasoning receipts."
      );
    }
    if (runState === "running") {
      return "Agent is processing this quarter...";
    }
    if (runState === "cancelled") {
      return "Agent run cancelled. Start another quarter to resume.";
    }
    if (runState === "error") {
      return "Agent run failed. Reset and retry to restore live activity.";
    }
    return "No thought events were captured for this quarter.";
  }, [idleHint, runState]);

  return (
    <section className={`rounded-xl border bg-[#0b0f14] p-4 ${panelClass}`}>
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span
            className={`h-2.5 w-2.5 rounded-full ${
              active
                ? "bg-emerald-400 shadow-[0_0_8px_rgba(74,222,128,0.7)] animate-pulse"
                : "bg-slate-500"
            }`}
          />
          <h3 className="font-mono text-xs font-semibold tracking-wide text-slate-200">Agent Activity</h3>
        </div>
        <span className="font-mono text-[11px] uppercase tracking-wide text-slate-400">{statusLabel}</span>
      </div>

      <div
        ref={viewportRef}
        className={`${compact ? "h-[224px]" : "h-[320px]"} space-y-2 overflow-y-auto rounded-lg border border-white/5 bg-black/20 px-2.5 py-2`}
      >
        {entries.length === 0 ? (
          <p className="px-1 py-2 font-mono text-xs leading-relaxed text-slate-500">{emptyMessage}</p>
        ) : null}
        {entries.map((entry, index) => {
          const style = typeStyles[entry.type];
          const narrative = entry.origin === "narrative";
          return (
            <div
              key={entry.id}
              className={`rounded-md border px-2 py-1.5 opacity-0 animate-fade-up ${
                narrative
                  ? "border-[var(--accent-border)] bg-[rgba(212,149,106,0.06)]"
                  : "border-white/5 bg-white/[0.02]"
              }`}
              style={{ animationDelay: `${Math.min(index * 70, 420)}ms` }}
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-[10px] text-slate-500">{toTimeLabel(entry.timestamp)}</span>
                <span className={`rounded border px-1.5 py-0.5 font-mono text-[10px] font-semibold ${style.badge}`}>
                  {style.label}
                </span>
                {narrative ? (
                  <span className="rounded border border-[var(--accent-border)] bg-[var(--accent-dim)] px-1.5 py-0.5 font-mono text-[10px] font-semibold text-[var(--accent)]">
                    Narrative cue
                  </span>
                ) : (
                  <span className="rounded border border-white/10 bg-white/[0.03] px-1.5 py-0.5 font-mono text-[10px] font-semibold text-slate-400">
                    Server
                  </span>
                )}
              </div>
              <p
                className={`mt-1 font-mono text-xs leading-relaxed ${
                  narrative ? "text-[#d8c5b6]" : style.text
                }`}
              >
                {entry.content}
              </p>
              {showMemorySources && entry.memoryRefs && entry.memoryRefs.length > 0 ? (
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {entry.memoryRefs.map((memoryId) => (
                    <button
                      key={`${entry.id}:${memoryId}`}
                      type="button"
                      onClick={() => onOpenMemoryRef?.(memoryId, entry)}
                      className={`rounded px-1.5 py-0.5 font-mono text-[11px] transition ${
                        narrative
                          ? "border border-[var(--accent-border)] bg-[var(--accent-dim)] text-[var(--accent)] hover:bg-[rgba(212,149,106,0.22)]"
                          : "border border-violet-300/35 bg-violet-500/10 text-violet-200 hover:bg-violet-500/20"
                      }`}
                    >
                      {memoryId}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </section>
  );
}
