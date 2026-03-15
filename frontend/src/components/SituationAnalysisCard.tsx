import { useCallback, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";

import { getSituationAnalysis } from "../api/client";
import { useVigilensStore } from "../store/useVigilensStore";
import type { SituationAnalysis } from "../types/shared";

const RISK_STYLES: Record<
  string,
  { bg: string; border: string; badge: string; label: string; dot: string }
> = {
  low: {
    bg: "from-emerald-500/[0.06] to-transparent",
    border: "border-emerald-500/20",
    badge: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
    label: "LOW RISK",
    dot: "bg-emerald-400",
  },
  moderate: {
    bg: "from-amber-500/[0.06] to-transparent",
    border: "border-amber-500/20",
    badge: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
    label: "MODERATE",
    dot: "bg-amber-400",
  },
  elevated: {
    bg: "from-orange-500/[0.06] to-transparent",
    border: "border-orange-500/20",
    badge: "bg-orange-500/15 text-orange-300 ring-orange-500/30",
    label: "ELEVATED",
    dot: "bg-orange-400",
  },
  high: {
    bg: "from-red-500/[0.06] to-transparent",
    border: "border-red-500/20",
    badge: "bg-red-500/15 text-red-300 ring-red-500/30",
    label: "HIGH RISK",
    dot: "bg-red-400",
  },
};

const MEMORY_BADGE_COLORS: Record<string, string> = {
  EventLog: "bg-sky-500/15 text-sky-300 ring-sky-500/25",
  Episodic: "bg-violet-500/15 text-violet-300 ring-violet-500/25",
  Profile: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/25",
  Foresight: "bg-amber-500/15 text-amber-300 ring-amber-500/25",
  EverMemOS: "bg-pink-500/15 text-pink-300 ring-pink-500/25",
};

function ShimmerBlock() {
  return (
    <div className="animate-pulse space-y-3">
      <div className="h-4 w-3/4 rounded bg-white/[0.06]" />
      <div className="h-4 w-full rounded bg-white/[0.06]" />
      <div className="h-4 w-5/6 rounded bg-white/[0.06]" />
      <div className="mt-4 h-4 w-2/3 rounded bg-white/[0.06]" />
      <div className="h-4 w-full rounded bg-white/[0.06]" />
      <div className="h-4 w-4/5 rounded bg-white/[0.06]" />
    </div>
  );
}

export interface SituationAnalysisCardProps {
  drugId: string;
  quarter: string | null;
}

export function SituationAnalysisCard({ drugId, quarter }: SituationAnalysisCardProps) {
  const situationAnalysis = useVigilensStore((s) => s.situationAnalysis);
  const situationLoading = useVigilensStore((s) => s.situationLoading);
  const setSituationAnalysis = useVigilensStore((s) => s.setSituationAnalysis);
  const setSituationLoading = useVigilensStore((s) => s.setSituationLoading);

  const [error, setError] = useState<string | null>(null);
  const cacheRef = useRef<Map<string, SituationAnalysis>>(new Map());
  const abortRef = useRef<AbortController | null>(null);

  const currentCacheKey = quarter ? `${drugId}::${quarter}` : null;
  const cachedForQuarter = currentCacheKey ? cacheRef.current.get(currentCacheKey) ?? null : null;

  const displayedAnalysis = cachedForQuarter ?? situationAnalysis;
  const isStale =
    !displayedAnalysis || (quarter != null && displayedAnalysis.quarter !== quarter);

  const analyzeQuarter = useCallback(async () => {
    if (!quarter) return;
    const cacheKey = `${drugId}::${quarter}`;
    const cached = cacheRef.current.get(cacheKey);
    if (cached) {
      setSituationAnalysis(cached);
      return;
    }

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setSituationLoading(true);
    setError(null);

    try {
      const result = await getSituationAnalysis(drugId, quarter, controller.signal);
      cacheRef.current.set(cacheKey, result);
      setSituationAnalysis(result);
    } catch (e: unknown) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      setError("Unable to generate situation analysis");
    } finally {
      setSituationLoading(false);
    }
  }, [drugId, quarter, setSituationAnalysis, setSituationLoading]);

  if (!quarter) return null;

  const shownAnalysis = isStale ? null : displayedAnalysis;
  const risk = shownAnalysis?.risk_level ?? "moderate";
  const style = RISK_STYLES[risk] ?? RISK_STYLES.moderate;

  return (
    <div
      className={`relative overflow-hidden rounded-xl border ${style.border} bg-gradient-to-br ${style.bg} backdrop-blur-sm`}
    >
      {/* top accent line */}
      <div className={`absolute inset-x-0 top-0 h-[2px] ${style.dot} opacity-60`} />

      <div className="px-5 py-4 sm:px-6">
        {/* header row */}
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-white/[0.06]">
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 20 20"
                fill="currentColor"
                className="h-4 w-4 text-[var(--accent)]"
              >
                <path d="M15.98 1.804a1 1 0 0 0-1.96 0l-.24 1.192a1 1 0 0 1-.784.785l-1.192.238a1 1 0 0 0 0 1.962l1.192.238a1 1 0 0 1 .785.785l.238 1.192a1 1 0 0 0 1.962 0l.238-1.192a1 1 0 0 1 .785-.785l1.192-.238a1 1 0 0 0 0-1.962l-1.192-.238a1 1 0 0 1-.785-.785l-.238-1.192ZM6.949 5.684a1 1 0 0 0-1.898 0l-.683 2.051a1 1 0 0 1-.633.633l-2.051.683a1 1 0 0 0 0 1.898l2.051.684a1 1 0 0 1 .633.632l.683 2.051a1 1 0 0 0 1.898 0l.683-2.051a1 1 0 0 1 .633-.633l2.051-.683a1 1 0 0 0 0-1.898l-2.051-.683a1 1 0 0 1-.633-.633L6.95 5.684ZM13.949 13.684a1 1 0 0 0-1.898 0l-.184.551a1 1 0 0 1-.632.633l-.551.183a1 1 0 0 0 0 1.898l.551.183a1 1 0 0 1 .633.633l.183.551a1 1 0 0 0 1.898 0l.184-.551a1 1 0 0 1 .632-.633l.551-.183a1 1 0 0 0 0-1.898l-.551-.184a1 1 0 0 1-.633-.632l-.183-.551Z" />
              </svg>
            </div>
            <h3 className="text-[15px] font-semibold tracking-wide text-[var(--text-primary)]">
              AI Situation Brief
            </h3>
          </div>

          <div className="flex items-center gap-2">
            {shownAnalysis && (
              <span className="text-[11px] text-[var(--text-tertiary)]">
                {shownAnalysis.quarter}
              </span>
            )}
            {shownAnalysis && (
              <span
                className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${style.badge}`}
              >
                <span className={`h-1.5 w-1.5 rounded-full ${style.dot}`} />
                {style.label}
              </span>
            )}
          </div>
        </div>

        {/* body */}
        <div className="mt-4">
          {situationLoading ? (
            <ShimmerBlock />
          ) : error ? (
            <p className="text-sm text-red-400/80">{error}</p>
          ) : shownAnalysis ? (
            <>
              <div className="max-w-none">
                <ReactMarkdown
                  components={{
                    p: ({ children }) => (
                      <p className="mb-3 text-sm font-[350] leading-[1.7] text-[var(--text-secondary)]">
                        {children}
                      </p>
                    ),
                    strong: ({ children }) => (
                      <strong className="font-semibold text-[var(--text-primary)]">{children}</strong>
                    ),
                    ul: ({ children }) => (
                      <ul className="mb-3 space-y-1 pl-4 list-disc">{children}</ul>
                    ),
                    ol: ({ children }) => (
                      <ol className="mb-3 space-y-1 pl-4 list-decimal">{children}</ol>
                    ),
                    li: ({ children }) => (
                      <li className="text-sm leading-[1.6] text-[var(--text-secondary)]">{children}</li>
                    ),
                    h3: ({ children }) => (
                      <h4 className="mb-1 mt-3 text-xs font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">
                        {children}
                      </h4>
                    ),
                    h4: ({ children }) => (
                      <h4 className="mb-1 mt-3 text-xs font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">
                        {children}
                      </h4>
                    ),
                    em: ({ children }) => (
                      <em className="text-[var(--text-secondary)] italic">{children}</em>
                    ),
                  }}
                >
                  {shownAnalysis.narrative}
                </ReactMarkdown>
              </div>

              {/* key changes */}
              {shownAnalysis.key_changes.length > 0 && (
                <div className="mt-4 rounded-lg border border-white/[0.06] bg-white/[0.02] px-4 py-3">
                  <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">
                    Key Changes This Quarter
                  </p>
                  <ul className="space-y-1">
                    {shownAnalysis.key_changes.map((change, i) => (
                      <li
                        key={i}
                        className="flex items-start gap-2 text-[13px] text-[var(--text-secondary)]"
                      >
                        <span className="mt-1.5 h-1 w-1 flex-shrink-0 rounded-full bg-[var(--accent)]" />
                        {change}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* memory sources footer */}
              <div className="mt-4 flex flex-wrap items-center gap-1.5">
                <span className="text-[10px] uppercase tracking-wider text-[var(--text-tertiary)]">
                  Memory sources:
                </span>
                {shownAnalysis.memory_sources.map((source) => (
                  <span
                    key={source}
                    className={`inline-flex rounded-full px-2 py-0.5 text-[10px] font-medium ring-1 ring-inset ${
                      MEMORY_BADGE_COLORS[source] ??
                      "bg-white/[0.06] text-[var(--text-tertiary)] ring-white/10"
                    }`}
                  >
                    {source}
                  </span>
                ))}
              </div>
            </>
          ) : (
            <div className="flex flex-col items-center gap-3 py-4">
              <p className="text-sm text-[var(--text-tertiary)]">
                Ready to analyze <span className="font-medium text-[var(--text-secondary)]">{quarter}</span>
              </p>
              <button
                type="button"
                onClick={analyzeQuarter}
                className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--accent)]/15 px-3.5 py-1.5 text-[13px] font-medium text-[var(--accent)] ring-1 ring-inset ring-[var(--accent)]/30 transition-all hover:bg-[var(--accent)]/25 hover:ring-[var(--accent)]/50 active:scale-[0.97]"
              >
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  viewBox="0 0 16 16"
                  fill="currentColor"
                  className="h-3.5 w-3.5"
                >
                  <path d="M15.98 1.804a1 1 0 0 0-1.96 0l-.24 1.192a1 1 0 0 1-.784.785l-1.192.238a1 1 0 0 0 0 1.962l1.192.238a1 1 0 0 1 .785.785l.238 1.192a1 1 0 0 0 1.962 0l.238-1.192a1 1 0 0 1 .785-.785l1.192-.238a1 1 0 0 0 0-1.962l-1.192-.238a1 1 0 0 1-.785-.785l-.238-1.192Z" />
                </svg>
                Analyze {quarter}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
