export interface MemoryReasoningLoopTraceProps {
  quarter: string | null;
  memoryStep: string;
  reasoningStep: string;
  actionStep: string;
}

export function MemoryReasoningLoopTrace({
  quarter,
  memoryStep,
  reasoningStep,
  actionStep,
}: MemoryReasoningLoopTraceProps) {
  return (
    <section className="rounded-xl border border-[var(--border)] bg-[var(--bg-panel)] p-4">
      <p className="text-[11px] font-medium uppercase tracking-wide text-[var(--text-tertiary)]">
        Memory {"->"} Reasoning {"->"} Action
      </p>
      <p className="mt-1 text-xs text-[var(--text-secondary)]">
        {quarter ? `Quarter ${quarter}` : "No active quarter selected."}
      </p>
      <div className="mt-3 space-y-2">
        <div className="rounded-md border border-violet-400/20 bg-violet-500/8 px-3 py-2">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-violet-300">Memory</p>
          <p className="mt-1 text-xs text-violet-100">{memoryStep}</p>
        </div>
        <div className="rounded-md border border-amber-300/20 bg-amber-500/8 px-3 py-2">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-amber-300">Reasoning</p>
          <p className="mt-1 text-xs text-amber-100">{reasoningStep}</p>
        </div>
        <div className="rounded-md border border-emerald-300/20 bg-emerald-500/8 px-3 py-2">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-emerald-300">Action</p>
          <p className="mt-1 text-xs text-emerald-100">{actionStep}</p>
        </div>
      </div>
    </section>
  );
}
