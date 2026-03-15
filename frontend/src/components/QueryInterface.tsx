import { useState } from "react";

import type { QueryResponse, SignalPoint } from "../types/shared";

export interface QueryInterfaceProps {
  drugId: string;
  activeQuarter: string | null;
  onSubmit: (question: string) => Promise<void>;
  response: QueryResponse | null;
  loading: boolean;
  onOpenEvidence?: (reportId: string) => void;
}

function signalSummary(point: SignalPoint): string {
  const ror = point.ror !== null ? point.ror.toFixed(2) : "-";
  const low = point.ror_ci_lower !== null ? point.ror_ci_lower.toFixed(2) : "-";
  const high = point.ror_ci_upper !== null ? point.ror_ci_upper.toFixed(2) : "-";
  return `${point.adverse_event}: ROR ${ror} (CI ${low}\u2013${high}) [${point.trajectory}]`;
}

export function QueryInterface({
  drugId,
  activeQuarter,
  onSubmit,
  response,
  loading,
  onOpenEvidence,
}: QueryInterfaceProps) {
  const [question, setQuestion] = useState("");
  const trimmedQuestion = question.trim();
  const canSubmit = Boolean(activeQuarter) && !loading && trimmedQuestion.length > 0;

  function submit(): void {
    if (!canSubmit) {
      return;
    }
    void onSubmit(trimmedQuestion);
  }

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-panel)] p-4">
      <h3 className="mb-2 text-xs font-medium tracking-wide text-[var(--text-tertiary)]">Query</h3>
      <p className="mb-2 text-xs text-[var(--text-secondary)]">
        Ask about {drugId} as of {activeQuarter ?? "a loaded quarter"}
      </p>
      <div className="flex gap-2">
        <input
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={(event) => {
            if (event.key !== "Enter") {
              return;
            }
            event.preventDefault();
            submit();
          }}
          placeholder="Are GI motility risks emerging?"
          className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg-card)] px-3 py-2 text-sm text-[var(--text-primary)] placeholder-[var(--text-tertiary)] outline-none transition focus:border-[var(--accent-border)]"
        />
        <button
          type="button"
          onClick={submit}
          disabled={!canSubmit}
          className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-medium text-[var(--bg-root)] transition hover:bg-[var(--accent-hover)] disabled:opacity-40"
        >
          Ask
        </button>
      </div>

      {!activeQuarter ? (
        <p className="mt-3 text-xs text-amber-300">Load at least one quarter before running a query.</p>
      ) : null}

      {loading ? (
        <p className="mt-3 text-sm text-[var(--text-secondary)]">Generating assessment\u2026</p>
      ) : null}

      {response ? (
        <div className="mt-3 space-y-2 rounded-lg bg-[var(--bg-card)] p-3 text-sm">
          <p className="font-mono text-xs text-[var(--accent)]">confidence: {response.confidence}</p>
          <p className="leading-relaxed text-[var(--text-primary)]">{response.answer_text}</p>
          <div className="font-mono text-xs text-[var(--text-secondary)]">
            {response.signal_summary.slice(0, 3).map((point) => (
              <p key={`${point.quarter}-${point.adverse_event}`}>{signalSummary(point)}</p>
            ))}
          </div>
          <div className="flex flex-wrap gap-1">
            {response.evidence.map((item) => (
              <button
                key={item.safetyreportid}
                type="button"
                onClick={() => onOpenEvidence?.(item.safetyreportid)}
                className="rounded-md bg-white/[0.04] px-2 py-0.5 font-mono text-xs text-[var(--accent)] transition hover:bg-white/[0.08]"
              >
                {item.safetyreportid}
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
