import { useState } from "react";

export interface AboutPanelProps {
  reportsLoaded: number;
  quartersLoaded: number;
  beliefCount: number;
  scorecardSummary: string;
  drugLabel: string;
  isPrimaryDemoDrug?: boolean;
}

export function AboutPanel({
  reportsLoaded,
  quartersLoaded,
  beliefCount,
  scorecardSummary,
  drugLabel,
  isPrimaryDemoDrug = false,
}: AboutPanelProps) {
  const [open, setOpen] = useState(false);

  return (
    <section className="mb-5 rounded-xl border border-[var(--accent-border)] bg-[var(--accent-dim)] p-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="font-display text-base text-[var(--accent)]">What is VigiLens?</h2>
        <button
          type="button"
          onClick={() => setOpen((current) => !current)}
          className="rounded-md bg-[var(--accent-dim)] px-2.5 py-1 text-xs font-medium text-[var(--accent)] transition hover:bg-[rgba(212,149,106,0.2)]"
        >
          {open ? "Hide" : "Show"}
        </button>
      </div>
      {open ? (
        <div className="mt-3 space-y-2 text-sm leading-relaxed text-[var(--text-secondary)]">
          <p>
            VigiLens is a memory-native pharmacovigilance agent. Postgres keeps the canonical FAERS ledger;
            EverMemOS augments temporal memory, provenance, and retrieval so the agent can change its
            interpretation as evidence accumulates.
          </p>
          <p>
            When anomalies emerge, the agent reasons over episodic history and the evolving drug
            profile, then revises its belief state. The signature behavior is retroactive reinterpretation:
            old reports are re-evaluated when new signals change the clinical meaning of earlier evidence.
          </p>
          <p>
            EverMemOS semantics in VigiLens: `group_id` is the isolation namespace per drug; MemCells
            and MemScenes are EverMemOS-internal layers generated from ingested messages, not aliases
            for database tables or IDs.
          </p>
          <p>
            Hierarchical memory flow: report-level facts feed EventLog memories, quarterly narratives
            become episodic recollection, profile memory tracks the drug’s evolving identity, and
            foresight memories preserve auditable regulatory alerts.
          </p>
          {isPrimaryDemoDrug ? (
            <p>
              Best first pass in the normal workspace: start with semaglutide, run the timeline through
              `2023-Q3`, watch the belief revision section change, then click `Show FDA receipt` to land on
              `2023-Q4` before opening the analyst workspace.
            </p>
          ) : (
            <p>
              This casefile is using the same monitoring stack for {drugLabel}. Search and add additional drugs from
              Discover, then use this workspace for quarter-by-quarter inspection and evidence review.
            </p>
          )}
          <p>
            Current loaded timeline: {reportsLoaded.toLocaleString("en-US")} real FAERS reports across{" "}
            {quartersLoaded} quarters, with {beliefCount} tracked belief snapshots and {scorecardSummary}.
          </p>
          <p>Memory types (EverMemOS):</p>
          <ul className="list-disc space-y-1 pl-5 text-[13px]">
            <li>EventLog: timestamped, citable FAERS report facts</li>
            <li>Episodic (MemScene-facing): quarterly safety narratives with context and tempo</li>
            <li>Profile: evolving drug safety identity over time</li>
            <li>Foresight: FDA-action predictions with confidence and validity window</li>
          </ul>
        </div>
      ) : null}
    </section>
  );
}
