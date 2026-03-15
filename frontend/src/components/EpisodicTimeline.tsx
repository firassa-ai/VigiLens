import { useEffect, useMemo, useRef, useState } from "react";

import type { EpisodicSummary } from "../types/shared";

export interface EpisodicTimelineProps {
  episodes: EpisodicSummary[];
  loading: boolean;
  showMemorySources?: boolean;
  currentQuarter?: string | null;
  onOpenMemory?: (episode: EpisodicSummary) => void;
}

function previewNarrative(narrative: string): string {
  const normalized = narrative.replace(/\s+/g, " ").trim();
  if (!normalized) {
    return "";
  }
  const sentences = normalized.split(/(?<=[.!?])\s+/).filter((chunk) => chunk.length > 0);
  if (sentences.length === 0) {
    return normalized;
  }
  return sentences.slice(0, 2).join(" ");
}

function shortMemoryId(memoryId: string): string {
  if (memoryId.length <= 10) {
    return memoryId;
  }
  return `${memoryId.slice(0, 8)}...`;
}

export function EpisodicTimeline({
  episodes,
  loading,
  showMemorySources = false,
  currentQuarter = null,
  onOpenMemory,
}: EpisodicTimelineProps) {
  const ordered = useMemo(() => [...episodes].sort((a, b) => a.quarter.localeCompare(b.quarter)), [episodes]);
  const [expandedQuarters, setExpandedQuarters] = useState<Set<string>>(new Set());
  const rowRefs = useRef<Record<string, HTMLDivElement | null>>({});

  useEffect(() => {
    if (!currentQuarter) {
      return;
    }
    const target = rowRefs.current[currentQuarter];
    if (target && typeof target.scrollIntoView === "function") {
      target.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [currentQuarter, ordered]);

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-panel)] p-4">
      <h3 className="mb-3 text-xs font-medium tracking-wide text-[var(--text-tertiary)]">
        Episodic Timeline
      </h3>
      {loading ? <div className="h-36 animate-pulse rounded-lg bg-[var(--bg-card)]" /> : null}
      {!loading && ordered.length === 0 ? (
        <p className="text-sm text-[var(--text-secondary)]">No episodes yet.</p>
      ) : null}
      <div className="max-h-[300px] space-y-2 overflow-auto pl-3" style={{ borderLeft: "2px solid var(--bg-elevated)" }}>
        {ordered.map((episode) => {
          const expanded = expandedQuarters.has(episode.quarter);
          const active = currentQuarter === episode.quarter;
          const signalText =
            episode.key_signals_mentioned.length > 0 ? episode.key_signals_mentioned.join(", ") : "none";
          return (
            <div
              key={episode.quarter}
              ref={(node) => {
                rowRefs.current[episode.quarter] = node;
              }}
              className={`animate-fade-up rounded-lg p-2.5 ${
                active
                  ? "bg-[var(--accent-dim)] ring-1 ring-[var(--accent-border)]"
                  : "bg-[var(--bg-card)]"
              }`}
            >
              <p className={`font-mono text-xs font-medium ${active ? "text-[var(--accent)]" : "text-[var(--text-primary)]"}`}>
                {episode.quarter}
              </p>
              <p className="mt-0.5 text-[11px] text-[var(--text-tertiary)]">
                {episode.report_count_ingested} reports &middot; Signals: {signalText}
              </p>
              <p className="mt-1 text-xs leading-relaxed text-[var(--text-secondary)]">
                {expanded ? episode.narrative : previewNarrative(episode.narrative)}
              </p>
              {episode.narrative.length > 120 ? (
                <button
                  type="button"
                  onClick={() =>
                    setExpandedQuarters((current) => {
                      const next = new Set(current);
                      if (next.has(episode.quarter)) {
                        next.delete(episode.quarter);
                      } else {
                        next.add(episode.quarter);
                      }
                      return next;
                    })
                  }
                  className="mt-1 text-[11px] font-medium text-[var(--accent)] hover:underline"
                >
                  {expanded ? "Show less" : "Show more"}
                </button>
              ) : null}
              <div className="mt-1.5 flex flex-wrap gap-1">
                <span className="rounded bg-white/[0.04] px-1.5 py-0.5 text-[11px] text-[var(--text-tertiary)]">
                  EverMemOS
                </span>
                <span className="rounded bg-white/[0.04] px-1.5 py-0.5 text-[11px] text-[var(--text-tertiary)]">
                  {episode.memory_source ?? "postgres_fallback"}
                </span>
                {episode.memory_id ? (
                  showMemorySources ? (
                    <>
                      <button
                        type="button"
                        onClick={() => onOpenMemory?.(episode)}
                        aria-label={episode.memory_id}
                        className="rounded bg-white/[0.04] px-1.5 py-0.5 text-[11px] text-[var(--text-tertiary)] transition hover:bg-white/[0.08] hover:text-[var(--text-primary)]"
                      >
                        {episode.quarter} Episode
                      </button>
                      <span className="rounded bg-white/[0.03] px-1.5 py-0.5 font-mono text-[11px] text-[var(--text-tertiary)]">
                        {shortMemoryId(episode.memory_id)}
                      </span>
                    </>
                  ) : (
                    <span className="rounded bg-white/[0.04] px-1.5 py-0.5 text-[11px] text-[var(--text-tertiary)]">
                      {episode.quarter} Episode
                    </span>
                  )
                ) : null}
              </div>
              {showMemorySources ? (
                <p className="mt-1 text-[11px] text-[var(--text-tertiary)]">
                  Source: EverMemOS Episodic Memory
                </p>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}
