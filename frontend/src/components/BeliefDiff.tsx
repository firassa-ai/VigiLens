import { useEffect, useMemo, useRef, useState } from "react";

import type { Belief, BeliefDiff as BeliefDiffType } from "../types/shared";

type BeliefGroup = "safety" | "gi" | "regulatory";

export interface BeliefDiffProps {
  beliefs: Belief[];
  diff: BeliefDiffType | null;
  onRequestDiff: (beforeId: string, afterId: string) => Promise<void>;
  onOpenEvidence?: (reportId: string) => void;
  loading: boolean;
  currentQuarter: string | null;
}

const groupLabels: Record<BeliefGroup, string> = {
  safety: "Safety Profile",
  gi: "GI Motility",
  regulatory: "Regulatory",
};

function beliefGroup(questionText: string): BeliefGroup {
  const lowered = questionText.toLowerCase();
  if (lowered.includes("gi motility") || lowered.includes("gastro") || lowered.includes("gastroparesis")) {
    return "gi";
  }
  if (lowered.includes("regulatory") || lowered.includes("warrant") || lowered.includes("attention")) {
    return "regulatory";
  }
  return "safety";
}

function sortQuarter(a: string, b: string): number {
  return a.localeCompare(b);
}

function latestBeliefPerQuarter(rows: Belief[]): Belief[] {
  const byQuarter = new Map<string, Belief>();
  for (const row of rows) {
    const current = byQuarter.get(row.quarter_context);
    if (!current || current.created_at < row.created_at) {
      byQuarter.set(row.quarter_context, row);
    }
  }
  return [...byQuarter.values()].sort((a, b) => sortQuarter(a.quarter_context, b.quarter_context));
}

function trim(value: string, max = 210): string {
  if (value.length <= max) {
    return value;
  }
  return `${value.slice(0, max).trimEnd()}\u2026`;
}

export function BeliefDiff({
  beliefs,
  diff,
  onRequestDiff,
  onOpenEvidence,
  loading,
  currentQuarter,
}: BeliefDiffProps) {
  const [selectedGroup, setSelectedGroup] = useState<BeliefGroup>("gi");
  const lastRequestedPair = useRef<string>("");

  const groupedBeliefs = useMemo(() => {
    const groups: Record<BeliefGroup, Belief[]> = { safety: [], gi: [], regulatory: [] };
    for (const belief of beliefs) {
      groups[beliefGroup(belief.question_text)].push(belief);
    }
    return {
      safety: latestBeliefPerQuarter(groups.safety),
      gi: latestBeliefPerQuarter(groups.gi),
      regulatory: latestBeliefPerQuarter(groups.regulatory),
    };
  }, [beliefs]);

  const selection = useMemo(() => {
    const rows = groupedBeliefs[selectedGroup];
    if (rows.length < 2) {
      return { before: null, after: null };
    }
    const before = rows[0];
    const after = currentQuarter
      ? rows.find((row) => row.quarter_context === currentQuarter) ?? rows[rows.length - 1]
      : rows[rows.length - 1];
    if (!before || !after || before.id === after.id) {
      return { before: null, after: null };
    }
    return { before, after };
  }, [currentQuarter, groupedBeliefs, selectedGroup]);

  useEffect(() => {
    if (!selection.before || !selection.after) {
      return;
    }
    const pairKey = `${selection.before.id}:${selection.after.id}`;
    const diffPairKey = diff ? `${diff.before.id}:${diff.after.id}` : "";
    if (lastRequestedPair.current === pairKey || diffPairKey === pairKey) {
      lastRequestedPair.current = pairKey;
      return;
    }
    lastRequestedPair.current = pairKey;
    void onRequestDiff(selection.before.id, selection.after.id);
  }, [diff, onRequestDiff, selection.after, selection.before]);

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-panel)] p-4">
      <h3 className="mb-3 text-xs font-medium tracking-wide text-[var(--text-tertiary)]">
        Belief Diff
      </h3>

      <div className="mb-3 flex gap-1">
        {(Object.keys(groupLabels) as BeliefGroup[]).map((key) => (
          <button
            key={key}
            type="button"
            onClick={() => setSelectedGroup(key)}
            className={`rounded-md px-2.5 py-1 text-xs font-medium transition ${
              selectedGroup === key
                ? "bg-[var(--accent-dim)] text-[var(--accent)]"
                : "text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-white/[0.04]"
            }`}
          >
            {groupLabels[key]}
          </button>
        ))}
      </div>

      {!selection.before || !selection.after ? (
        <p className="text-sm text-[var(--text-secondary)]">Need at least two quarters to compare.</p>
      ) : null}

      {loading ? <div className="h-16 animate-pulse rounded-lg bg-[var(--bg-card)]" /> : null}

      {diff ? (
        <div className="space-y-3">
          <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
            <div className="rounded-lg bg-[var(--bg-card)] p-3 text-xs">
              <p className="font-mono font-medium text-[var(--text-secondary)]">{diff.before.quarter_context}</p>
              <p className="mt-1 text-[var(--text-tertiary)]">Confidence: {diff.before.confidence_score}</p>
              <p className="mt-2 leading-relaxed text-[var(--text-secondary)]">{trim(diff.before.answer_text)}</p>
            </div>
            <div className="rounded-lg border border-[var(--accent-border)] bg-[var(--accent-dim)] p-3 text-xs">
              <p className="font-mono font-medium text-[var(--accent)]">{diff.after.quarter_context}</p>
              <p className="mt-1 text-[var(--text-secondary)]">Confidence: {diff.after.confidence_score}</p>
              <p className="mt-2 leading-relaxed text-[var(--text-secondary)]">{trim(diff.after.answer_text)}</p>
            </div>
          </div>

          <div className="flex gap-4 text-xs text-[var(--text-secondary)]">
            <span className="font-mono font-medium text-[var(--text-primary)]">
              Delta confidence: {diff.confidence_delta >= 0 ? `+${diff.confidence_delta}` : diff.confidence_delta}
            </span>
            <span>
              Reinterpreted: <span className="font-mono font-medium text-amber-300">{diff.reinterpreted_report_ids.length}</span>
            </span>
          </div>

          {diff.reinterpreted_report_ids.length > 0 ? (
            <div className="flex flex-wrap gap-1">
              {diff.reinterpreted_report_ids.map((id) => (
                <button
                  key={`reinterpret-${id}`}
                  type="button"
                  onClick={() => onOpenEvidence?.(id)}
                  className="rounded-md bg-amber-500/8 px-2 py-0.5 font-mono text-xs text-amber-300 transition hover:bg-amber-500/15"
                >
                  {id}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
