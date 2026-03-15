import { useEffect, useMemo, useRef, useState } from "react";

import type { Belief, SignalPoint } from "../types/shared";

type BeliefTabKey = "safety" | "gi" | "regulatory";

export interface KnowledgeTimeExplorerProps {
  quarters: string[];
  selectedQuarter: string | null;
  isPlaying: boolean;
  speedMs: number;
  onChangeQuarter: (quarter: string) => void;
  onTogglePlay: () => void;
  onStep: (delta: number) => void;
  onJumpStart: () => void;
  onJumpEnd: () => void;
  onSpeedMsChange: (value: number) => void;
  signalSnapshot: SignalPoint[];
  beliefsCurrentQuarter: Belief[];
  beliefsPreviousQuarter: Belief[];
  reinterpretationCount?: number;
  showMemorySources?: boolean;
  forcedBeliefTab?: BeliefTabKey | null;
  onOpenEpisodicMemory?: (memoryId: string, belief: Belief) => void;
}

function formatRor(value: number | null): string {
  if (value === null || Number.isNaN(value)) {
    return "-";
  }
  return value.toFixed(2);
}

function trimText(value: string, max = 180): string {
  if (value.length <= max) {
    return value;
  }
  return `${value.slice(0, max).trimEnd()}\u2026`;
}

type ParsedBeliefSignal = {
  signal: string;
  ror: string;
  trajectory: string;
};

type ParsedBeliefAnswer = {
  conclusion: string;
  signalRows: ParsedBeliefSignal[];
  supportingText: string;
};

function parseBeliefAnswer(answerText: string): ParsedBeliefAnswer {
  const lines = answerText
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);

  const conclusion = lines[0] ?? "";
  const signalRows: ParsedBeliefSignal[] = [];
  const supporting: string[] = [];
  const signalPattern = /^-\s*([^:]+):\s*ROR\s*([0-9.]+|-)\s*\(CI\s*[^)]*\),\s*([a-z_ ]+)\s*trajectory\.?$/i;

  for (const line of lines.slice(1)) {
    const match = signalPattern.exec(line);
    if (match) {
      signalRows.push({
        signal: match[1].trim(),
        ror: match[2].trim(),
        trajectory: match[3].trim(),
      });
      continue;
    }
    supporting.push(line.startsWith("- ") ? line.slice(2) : line);
  }

  return {
    conclusion,
    signalRows,
    supportingText: supporting.join(" "),
  };
}

function confidenceStyle(score: number): { barClass: string; textClass: string } {
  if (score > 80) {
    return {
      barClass: "bg-emerald-400",
      textClass: "text-emerald-300",
    };
  }
  if (score >= 60) {
    return {
      barClass: "bg-amber-400",
      textClass: "text-amber-300",
    };
  }
  return {
    barClass: "bg-red-400",
    textClass: "text-red-300",
  };
}

function shortMemoryId(value: string): string {
  if (value.length <= 10) {
    return value;
  }
  return `${value.slice(0, 8)}...`;
}

function beliefTabForQuestion(questionText: string): BeliefTabKey {
  const lowered = questionText.toLowerCase();
  if (lowered.includes("gi motility") || lowered.includes("gastro") || lowered.includes("gastroparesis")) {
    return "gi";
  }
  if (lowered.includes("regulatory") || lowered.includes("warrant") || lowered.includes("attention")) {
    return "regulatory";
  }
  return "safety";
}

function isReportEvidenceQuestion(questionText: string): boolean {
  return questionText.toLowerCase().includes("report-level evidence supports");
}

function beliefPriorityForTab(tab: BeliefTabKey, belief: Belief): number {
  const lowered = belief.question_text.toLowerCase();
  const evidencePenalty = isReportEvidenceQuestion(belief.question_text) ? 10 : 0;

  if (tab === "safety") {
    if (lowered.includes("overall safety profile")) {
      return 0;
    }
    return evidencePenalty + 5;
  }

  if (tab === "gi") {
    if (
      lowered.includes("emerging gi motility concerns") ||
      lowered.includes("gastrointestinal") ||
      lowered.includes("gastroparesis")
    ) {
      return 0;
    }
    return evidencePenalty + 5;
  }

  if (
    lowered.includes("regulatory") ||
    lowered.includes("warrant") ||
    lowered.includes("attention")
  ) {
    return 0;
  }

  return evidencePenalty + 5;
}

const tabLabels: Record<BeliefTabKey, string> = {
  safety: "Safety Profile",
  gi: "GI Motility",
  regulatory: "Regulatory",
};

const preferredBeliefTabOrder: BeliefTabKey[] = ["gi", "safety", "regulatory"];

function pickPreferredBeliefTab(beliefsByTab: Map<BeliefTabKey, Belief>): BeliefTabKey | null {
  for (const tab of preferredBeliefTabOrder) {
    if (beliefsByTab.has(tab)) {
      return tab;
    }
  }

  return beliefsByTab.keys().next().value ?? null;
}

export function KnowledgeTimeExplorer({
  quarters,
  selectedQuarter,
  isPlaying,
  speedMs,
  onChangeQuarter,
  onTogglePlay,
  onStep,
  onJumpStart,
  onJumpEnd,
  onSpeedMsChange,
  signalSnapshot,
  beliefsCurrentQuarter,
  beliefsPreviousQuarter,
  reinterpretationCount = 0,
  showMemorySources = false,
  forcedBeliefTab = null,
  onOpenEpisodicMemory,
}: KnowledgeTimeExplorerProps) {
  const [activeBeliefTab, setActiveBeliefTab] = useState<BeliefTabKey | null>(null);
  const [beliefCardUpdating, setBeliefCardUpdating] = useState(false);
  const lastAnimatedBeliefId = useRef<string | null>(null);

  const quarterIndex = useMemo(() => {
    if (!selectedQuarter) {
      return 0;
    }
    const idx = quarters.indexOf(selectedQuarter);
    return idx >= 0 ? idx : 0;
  }, [quarters, selectedQuarter]);

  const previousBeliefByHash = useMemo(() => {
    return new Map(beliefsPreviousQuarter.map((belief) => [belief.question_hash, belief]));
  }, [beliefsPreviousQuarter]);

  const beliefsByTab = useMemo(() => {
    const grouped = new Map<BeliefTabKey, Belief[]>();
    for (const belief of beliefsCurrentQuarter) {
      const tab = beliefTabForQuestion(belief.question_text);
      const current = grouped.get(tab) ?? [];
      current.push(belief);
      grouped.set(tab, current);
    }
    const byTab = new Map<BeliefTabKey, Belief>();
    for (const [tab, beliefsForTab] of grouped.entries()) {
      const chosen = [...beliefsForTab].sort((a, b) => {
        const priorityDelta = beliefPriorityForTab(tab, a) - beliefPriorityForTab(tab, b);
        if (priorityDelta !== 0) {
          return priorityDelta;
        }
        if (a.created_at !== b.created_at) {
          return a.created_at < b.created_at ? 1 : -1;
        }
        return a.question_text.localeCompare(b.question_text);
      })[0];
      if (chosen) {
        byTab.set(tab, chosen);
      }
    }
    return byTab;
  }, [beliefsCurrentQuarter]);

  const resolvedActiveBeliefTab = useMemo(
    () => activeBeliefTab ?? pickPreferredBeliefTab(beliefsByTab),
    [activeBeliefTab, beliefsByTab],
  );

  const activeBelief = useMemo(() => {
    return (
      (resolvedActiveBeliefTab ? beliefsByTab.get(resolvedActiveBeliefTab) : null) ??
      beliefsCurrentQuarter[0] ??
      null
    );
  }, [resolvedActiveBeliefTab, beliefsByTab, beliefsCurrentQuarter]);

  const parsedBelief = useMemo(() => {
    if (!activeBelief) {
      return null;
    }
    return parseBeliefAnswer(activeBelief.answer_text);
  }, [activeBelief]);

  useEffect(() => {
    if (!forcedBeliefTab) {
      return;
    }
    setActiveBeliefTab(forcedBeliefTab);
  }, [forcedBeliefTab]);

  useEffect(() => {
    if (forcedBeliefTab || beliefsByTab.size === 0) {
      return;
    }

    const nextTab = activeBeliefTab && beliefsByTab.has(activeBeliefTab)
      ? activeBeliefTab
      : pickPreferredBeliefTab(beliefsByTab);
    if (nextTab && nextTab !== activeBeliefTab) {
      setActiveBeliefTab(nextTab);
    }
  }, [activeBeliefTab, beliefsByTab, forcedBeliefTab]);

  useEffect(() => {
    if (!activeBelief) {
      return;
    }
    const previous = previousBeliefByHash.get(activeBelief.question_hash);
    if (!previous || previous.answer_text === activeBelief.answer_text) {
      return;
    }
    if (lastAnimatedBeliefId.current === activeBelief.id) {
      return;
    }
    lastAnimatedBeliefId.current = activeBelief.id;
    setBeliefCardUpdating(true);
    const timer = window.setTimeout(() => setBeliefCardUpdating(false), 650);
    return () => window.clearTimeout(timer);
  }, [activeBelief, previousBeliefByHash, selectedQuarter]);

  if (quarters.length === 0 || !selectedQuarter) {
    return (
      <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-panel)] p-4">
        <h3 className="font-display text-base text-[var(--text-primary)]">Time Travel</h3>
        <p className="mt-1 text-xs text-[var(--text-secondary)]">
          Browse knowledge at any point in time
        </p>
        <p className="mt-3 text-sm text-[var(--text-secondary)]">
          No quarters loaded. Use the demo controls or analyst workspace to ingest the first quarter.
        </p>
      </div>
    );
  }

  const loadedThrough = quarters[quarters.length - 1] ?? "-";

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-panel)] p-4">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h3 className="font-display text-base text-[var(--text-primary)]">Time Travel</h3>
          <p className="mt-0.5 text-xs text-[var(--text-secondary)]">
            Data loaded through: {loadedThrough} | Viewing: {selectedQuarter}
          </p>
        </div>
        <span className="rounded-md bg-[var(--accent-dim)] px-2 py-0.5 font-mono text-xs font-medium text-[var(--accent)]">
          {selectedQuarter}
        </span>
      </div>

      <input
        type="range"
        min={0}
        max={Math.max(quarters.length - 1, 0)}
        value={quarterIndex}
        onChange={(event) => {
          const nextIndex = Number(event.target.value);
          const quarter = quarters[nextIndex];
          if (quarter) {
            onChangeQuarter(quarter);
          }
        }}
        className="w-full"
      />

      <div className="mt-3 flex gap-1">
        <button type="button" onClick={onJumpStart} className="flex-1 rounded-md bg-white/[0.03] px-2 py-1.5 text-[11px] text-[var(--text-secondary)] transition hover:bg-white/[0.06]">
          Start
        </button>
        <button type="button" onClick={() => onStep(-1)} className="flex-1 rounded-md bg-white/[0.03] px-2 py-1.5 text-[11px] text-[var(--text-secondary)] transition hover:bg-white/[0.06]">
          Prev
        </button>
        <button
          type="button"
          onClick={onTogglePlay}
          className="flex-1 rounded-md bg-[var(--accent-dim)] px-2 py-1.5 text-[11px] font-semibold text-[var(--accent)] transition hover:bg-[rgba(212,149,106,0.2)]"
        >
          {isPlaying ? "Pause" : "Play"}
        </button>
        <button type="button" onClick={() => onStep(1)} className="flex-1 rounded-md bg-white/[0.03] px-2 py-1.5 text-[11px] text-[var(--text-secondary)] transition hover:bg-white/[0.06]">
          Next
        </button>
        <button type="button" onClick={onJumpEnd} className="flex-1 rounded-md bg-white/[0.03] px-2 py-1.5 text-[11px] text-[var(--text-secondary)] transition hover:bg-white/[0.06]">
          End
        </button>
      </div>

      <div className="mt-3 flex items-center justify-between text-xs text-[var(--text-secondary)]">
        <span>Speed</span>
        <select
          value={String(speedMs)}
          onChange={(event) => {
            onSpeedMsChange(Number(event.target.value));
          }}
          className="rounded-md border border-[var(--border)] bg-[var(--bg-card)] px-2 py-1 text-xs text-[var(--text-primary)]"
        >
          <option value="1400">1x</option>
          <option value="800">2x</option>
          <option value="450">4x</option>
        </select>
      </div>

      <div className="mt-4 space-y-4">
        <div>
          <p className="mb-1.5 text-xs font-medium text-[var(--text-tertiary)]">Agent Attention State</p>
          <div className="space-y-1.5">
            {signalSnapshot.length === 0 ? (
              <p className="text-xs text-[var(--text-secondary)]">No signals this quarter.</p>
            ) : null}
            {signalSnapshot.slice(0, 3).map((point) => (
              <div key={point.adverse_event} className="rounded-lg bg-[var(--bg-card)] p-2.5 text-xs">
                <p className="font-medium text-[var(--text-primary)]">{point.adverse_event}</p>
                <p className="mt-0.5 font-mono text-[var(--text-secondary)]">
                  ROR {formatRor(point.ror)} &middot; CI {formatRor(point.ror_ci_lower)}&ndash;{formatRor(point.ror_ci_upper)}
                </p>
                <p className="text-[var(--text-tertiary)]">{point.trajectory}</p>
              </div>
            ))}
          </div>
        </div>

        <div>
          <p className="mb-1.5 text-xs font-medium text-[var(--text-tertiary)]">Agent Belief State</p>
          <div className="mb-2 flex gap-1">
            {(Object.keys(tabLabels) as BeliefTabKey[]).map((key) => (
              <button
                key={key}
                type="button"
                onClick={() => setActiveBeliefTab(key)}
                className={`rounded-md px-2 py-1 text-[11px] font-medium transition ${
                  resolvedActiveBeliefTab === key
                    ? "bg-[var(--accent-dim)] text-[var(--accent)]"
                    : "text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-white/[0.04]"
                }`}
              >
                {tabLabels[key]}
              </button>
            ))}
          </div>

          {beliefsCurrentQuarter.length === 0 ? (
            <p className="text-xs text-[var(--text-secondary)]">No beliefs for this quarter.</p>
          ) : null}

          {activeBelief ? (
            <div className={`rounded-lg bg-[var(--bg-card)] p-3 text-xs ${beliefCardUpdating ? "belief-card-updating" : ""}`}>
              <p className="font-medium text-[var(--text-primary)]">
                {trimText(activeBelief.question_text, 120)}
              </p>
              {parsedBelief?.conclusion ? (
                <p className="mt-2 rounded-md border border-[var(--accent-border)] bg-[var(--accent-dim)] px-2 py-1.5 text-[13px] font-semibold leading-relaxed text-[var(--text-primary)]">
                  {parsedBelief.conclusion}
                </p>
              ) : (
                <p className="mt-2 leading-relaxed text-[var(--text-secondary)]">
                  {trimText(activeBelief.answer_text, 260)}
                </p>
              )}

              {parsedBelief && parsedBelief.signalRows.length > 0 ? (
                <div className="mt-2 overflow-hidden rounded-md border border-[var(--border)]">
                  <div className="grid grid-cols-[1.2fr_0.5fr_0.8fr] bg-white/[0.03] px-2 py-1 text-[10px] uppercase tracking-wide text-[var(--text-tertiary)]">
                    <span>Signal</span>
                    <span>ROR</span>
                    <span>Trajectory</span>
                  </div>
                  {parsedBelief.signalRows.slice(0, 6).map((row) => (
                    <div
                      key={`${activeBelief.id}:${row.signal}`}
                      className="grid grid-cols-[1.2fr_0.5fr_0.8fr] border-t border-white/[0.04] px-2 py-1 text-[11px] text-[var(--text-secondary)]"
                    >
                      <span className="truncate">{row.signal}</span>
                      <span className="font-mono">{row.ror}</span>
                      <span>{row.trajectory}</span>
                    </div>
                  ))}
                </div>
              ) : null}

              {parsedBelief?.supportingText ? (
                <p className="mt-2 leading-relaxed text-[var(--text-secondary)]">
                  {trimText(parsedBelief.supportingText, 220)}
                </p>
              ) : null}

              <div className="mt-2 text-[var(--text-tertiary)]">
                <div className="flex items-center justify-between">
                  <span className={`font-mono ${confidenceStyle(activeBelief.confidence_score).textClass}`}>
                    conf {activeBelief.confidence_score}
                  </span>
                  {(() => {
                    const prev = previousBeliefByHash.get(activeBelief.question_hash);
                    if (!prev) {
                      return <span className="rounded-md bg-[var(--accent-dim)] px-1.5 py-0.5 text-[var(--accent)]">new</span>;
                    }
                    const delta = activeBelief.confidence_score - prev.confidence_score;
                    if (Math.abs(delta) >= 5) {
                      return (
                        <span className={`rounded-md px-1.5 py-0.5 ${delta >= 0 ? "bg-emerald-500/10 text-emerald-300" : "bg-red-500/10 text-red-300"}`}>
                          {delta >= 0 ? "\u2191" : "\u2193"} {delta >= 0 ? `+${delta}` : delta}
                        </span>
                      );
                    }
                    return <span>{delta >= 0 ? `+${delta}` : delta}</span>;
                  })()}
                </div>
                <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
                  <div
                    className={`h-full rounded-full ${confidenceStyle(activeBelief.confidence_score).barClass}`}
                    style={{ width: `${Math.max(0, Math.min(100, activeBelief.confidence_score))}%` }}
                  />
                </div>
              </div>
              {reinterpretationCount > 0 ? (
                <p className="mt-2 rounded-md bg-amber-500/8 px-2 py-1 text-amber-300">
                  {reinterpretationCount} earlier reports reinterpreted
                </p>
              ) : null}
              {showMemorySources ? (
                <div className="mt-2 rounded-md bg-[var(--bg-elevated)] px-2 py-1.5 text-[var(--text-secondary)]">
                  <p>Grounded in {activeBelief.episodic_ids_used.length} episodic memories</p>
                  {activeBelief.episodic_ids_used.length > 0 ? (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {activeBelief.episodic_ids_used.slice(0, 4).map((memoryId) => (
                        <button
                          key={memoryId}
                          type="button"
                          onClick={() => onOpenEpisodicMemory?.(memoryId, activeBelief)}
                          aria-label={memoryId}
                          title={memoryId}
                          className="rounded bg-white/[0.04] px-1.5 py-0.5 font-mono text-[11px] text-[var(--text-tertiary)] transition hover:bg-white/[0.08] hover:text-[var(--text-primary)]"
                        >
                          {shortMemoryId(memoryId)}
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
