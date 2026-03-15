import { useEffect, useState } from "react";

import { buildForesightMemoryId } from "../lib/memoryProvenance";
import {
  countScorecardEntries,
  splitScorecardEntries,
} from "../lib/scorecardPresentation";
import type { ScorecardEntry } from "../types/shared";

type DemoStage = "baseline" | "reveal" | "validation" | "analyst";

export interface PredictionScorecardProps {
  entries: ScorecardEntry[];
  loading: boolean;
  asOfQuarter?: string | null;
  hiddenFutureCount?: number;
  showMemorySources?: boolean;
  onOpenForesightMemory?: (entry: ScorecardEntry, memoryId: string) => void;
  demoStage?: DemoStage;
  presentationMode?: "demo" | "generic";
  receiptSummary?: string | null;
  watchlistSummary?: string | null;
}

const resultStyles: Record<
  string,
  { bg: string; text: string; dot: string; border: string }
> = {
  validated: {
    bg: "bg-emerald-500/8",
    text: "text-emerald-300",
    dot: "bg-emerald-400",
    border: "border-emerald-500/20",
  },
  early: {
    bg: "bg-blue-500/8",
    text: "text-blue-300",
    dot: "bg-blue-400",
    border: "border-blue-500/20",
  },
  missed: {
    bg: "bg-red-500/8",
    text: "text-red-300",
    dot: "bg-red-400",
    border: "border-red-500/20",
  },
  pending: {
    bg: "bg-amber-500/8",
    text: "text-amber-300",
    dot: "bg-amber-400",
    border: "border-amber-500/20",
  },
};

const archivedResultStyle = {
  bg: "bg-white/[0.03]",
  text: "text-[var(--text-secondary)]",
  dot: "bg-white/40",
  border: "border-white/10",
};

const verificationStyles: Record<
  string,
  { border: string; badge: string; text: string }
> = {
  supported: {
    border: "border-emerald-500/20",
    badge: "bg-emerald-500/12 text-emerald-200",
    text: "text-emerald-100",
  },
  mixed: {
    border: "border-amber-500/20",
    badge: "bg-amber-500/12 text-amber-200",
    text: "text-amber-100",
  },
  unverified: {
    border: "border-red-500/20",
    badge: "bg-red-500/12 text-red-200",
    text: "text-red-100",
  },
  not_run: {
    border: "border-white/10",
    badge: "bg-white/[0.06] text-[var(--text-secondary)]",
    text: "text-[var(--text-secondary)]",
  },
};

function humanizeToken(value: string): string {
  return value.replaceAll("_", " ");
}

function quarterToDate(quarter: string): Date | null {
  const match = /^(\d{4})-Q([1-4])$/.exec(quarter);
  if (!match) {
    return null;
  }
  const year = Number(match[1]);
  const q = Number(match[2]);
  const month = (q - 1) * 3;
  return new Date(Date.UTC(year, month, 1));
}

function monthsLead(
  createdQuarter: string,
  actualDateIso: string,
): number | null {
  const created = quarterToDate(createdQuarter);
  const actual = new Date(actualDateIso);
  if (!created || Number.isNaN(actual.getTime()) || actual < created) {
    return null;
  }
  const years = actual.getUTCFullYear() - created.getUTCFullYear();
  const months = actual.getUTCMonth() - created.getUTCMonth();
  return years * 12 + months;
}

function formatFdaDate(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) {
    return iso;
  }
  return parsed.toLocaleDateString("en-US", {
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

function titleForEntry(entry: ScorecardEntry): string {
  return `${entry.prediction.adverse_event} -> ${entry.prediction.predicted_action.replace("_", " ")}`;
}

function orderEntries(entries: ScorecardEntry[]): ScorecardEntry[] {
  return [...entries].sort((a, b) => {
    const rank = { validated: 0, early: 1, pending: 2, missed: 3 } as const;
    if (rank[a.result] !== rank[b.result]) {
      return rank[a.result] - rank[b.result];
    }
    const aIleus = a.prediction.adverse_event === "Ileus" ? 0 : 1;
    const bIleus = b.prediction.adverse_event === "Ileus" ? 0 : 1;
    if (aIleus !== bIleus) {
      return aIleus - bIleus;
    }
    return a.prediction.created_at_quarter.localeCompare(
      b.prediction.created_at_quarter,
    );
  });
}

function stageSummary(params: {
  presentationMode: "demo" | "generic";
  demoStage: DemoStage;
  validated: number;
  pending: number;
  early: number;
  primaryEntry: ScorecardEntry | null;
  receiptSummary: string | null;
  watchlistSummary: string | null;
}): string {
  const {
    presentationMode,
    demoStage,
    validated,
    pending,
    early,
    primaryEntry,
    receiptSummary,
    watchlistSummary,
  } = params;
  const openCount = pending + early;
  const openLabel =
    openCount === 0
      ? null
      : `${openCount} ${openCount === 1 ? "open follow-up" : "open follow-ups"}`;
  if (presentationMode === "generic") {
    if (receiptSummary) {
      return `${receiptSummary}${watchlistSummary ? ` ${watchlistSummary}` : ""}`.trim();
    }
    if (pending > 0) {
      return `${pending} regulatory receipt forecast${pending === 1 ? "" : "s"} are open for follow-up.`;
    }
    return (
      watchlistSummary ??
      "Regulatory receipts stay conservative. Proof-backed signals and watchlist alerts appear in the casefile header."
    );
  }
  if (demoStage === "validation") {
    return primaryEntry?.actual_fda_action
      ? `Primary receipt: ${primaryEntry.actual_fda_action.title}. Additional tracked outcomes stay visible below.`
      : "Primary receipt is now in focus. Additional tracked outcomes stay visible below.";
  }
  if (demoStage === "reveal") {
    if (openLabel) {
      return `${validated} validated receipt${validated === 1 ? "" : "s"} and ${openLabel} as of this reveal quarter.`;
    }
    return `${validated} validated receipt${validated === 1 ? "" : "s"} as of this reveal quarter.`;
  }
  if (demoStage === "analyst") {
    return "Full scorecard context is available here, including class-scope actions and memory receipts.";
  }
  return "Forecasts become receipts as the case advances. Open the FDA link to verify each grounded action.";
}

function scoreLine(
  validated: number,
  pending: number,
  early: number,
  resolved: number,
): string {
  const openSegments: string[] = [];
  if (pending > 0) {
    openSegments.push(`${pending} pending`);
  }
  if (early > 0) {
    openSegments.push(`${early} early`);
  }
  if (openSegments.length > 0) {
    return `${validated} validated + ${openSegments.join(" + ")} receipts`;
  }
  if (resolved <= 0) {
    return "No resolved receipts";
  }
  return `${validated}/${resolved} resolved`;
}

function pickPrimaryEntry(
  entries: ScorecardEntry[],
  demoStage: DemoStage,
  presentationMode: "demo" | "generic",
): ScorecardEntry | null {
  if (entries.length === 0) {
    return null;
  }
  if (presentationMode === "generic") {
    return entries.find((entry) => entry.result === "validated") ?? entries[0];
  }
  if (demoStage === "validation") {
    return (
      entries.find((entry) => entry.prediction.adverse_event === "Ileus") ??
      entries[0]
    );
  }
  if (demoStage === "reveal") {
    return entries.find((entry) => entry.result === "validated") ?? entries[0];
  }
  return entries[0];
}

function EntryCard({
  entry,
  showMemorySources,
  onOpenForesightMemory,
  subdued = false,
  resultLabel,
  archived = false,
}: {
  entry: ScorecardEntry;
  showMemorySources: boolean;
  onOpenForesightMemory?: (entry: ScorecardEntry, memoryId: string) => void;
  subdued?: boolean;
  resultLabel?: string;
  archived?: boolean;
}) {
  const style = archived
    ? archivedResultStyle
    : (resultStyles[entry.result] ?? resultStyles.pending);
  const leadMonths = entry.actual_fda_action
    ? monthsLead(
        entry.prediction.created_at_quarter,
        entry.actual_fda_action.date,
      )
    : null;
  const foresightMemoryId = buildForesightMemoryId(
    entry.prediction.drug_id,
    entry.prediction.created_at_quarter,
  );
  const verification = entry.prediction.verification ?? null;
  const verificationStyle = verification
    ? (verificationStyles[verification.status] ?? verificationStyles.not_run)
    : null;

  return (
    <div
      className={`rounded-lg border p-3 ${style.bg} ${style.border} ${subdued ? "opacity-80" : ""}`}
    >
      <div className="flex items-center gap-2">
        <span className={`h-1.5 w-1.5 rounded-full ${style.dot}`} />
        <span className={`text-xs font-semibold ${style.text}`}>
          {resultLabel ?? entry.result.toUpperCase()}
        </span>
      </div>
      <p className="mt-1 text-sm font-medium text-[var(--text-primary)]">
        {titleForEntry(entry)}
      </p>
      <p className="mt-1 text-xs text-[var(--text-secondary)]">
        Predicted: {entry.prediction.created_at_quarter}
        {entry.actual_fda_action
          ? ` | Actual: ${formatFdaDate(entry.actual_fda_action.date)}`
          : ""}
      </p>

      <div className="mt-2 flex flex-wrap gap-1">
        <span className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--text-secondary)]">
          {humanizeToken(entry.prediction.basis.type)}
        </span>
        {entry.prediction.scope ? (
          <span className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--text-secondary)]">
            {entry.prediction.scope.label}
          </span>
        ) : null}
        {entry.actual_fda_action?.scope ? (
          <span className="rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-emerald-200">
            FDA scope {entry.actual_fda_action.scope.label}
          </span>
        ) : null}
      </div>

      <p className="mt-2 text-xs leading-relaxed text-[var(--text-tertiary)]">
        {entry.prediction.basis.summary}
      </p>
      <p className="mt-1 text-xs text-[var(--text-secondary)]">
        Supporting event: {entry.prediction.supporting_event.adverse_event} in{" "}
        {entry.prediction.supporting_event.quarter}
        {typeof entry.prediction.supporting_event.cumulative_count === "number"
          ? ` (${entry.prediction.supporting_event.cumulative_count} cumulative reports)`
          : ""}
      </p>
      {verification && verificationStyle ? (
        <div
          className={`mt-2 rounded-md border px-2.5 py-2 ${verificationStyle.border}`}
        >
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] ${verificationStyle.badge}`}
            >
              Proof {humanizeToken(verification.status)}
            </span>
            {verification.source_types.length > 0 ? (
              <span className="text-[10px] text-[var(--text-tertiary)]">
                Sources:{" "}
                {verification.source_types.map(humanizeToken).join(", ")}
              </span>
            ) : null}
          </div>
          <p
            className={`mt-1 text-xs leading-relaxed ${verificationStyle.text}`}
          >
            {verification.summary}
          </p>
          {verification.citations.length > 0 ? (
            <div className="mt-2 flex flex-wrap gap-2">
              {verification.citations.slice(0, 3).map((citation) => (
                <a
                  key={citation.url}
                  href={citation.url}
                  target="_blank"
                  rel="noreferrer"
                  className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[10px] text-[var(--accent)] underline decoration-[var(--accent)]/30 hover:decoration-[var(--accent)]"
                >
                  {citation.title}
                </a>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
      {entry.actual_fda_action ? (
        <a
          href={entry.actual_fda_action.source_url}
          target="_blank"
          rel="noreferrer"
          className="mt-1 inline-block text-xs text-[var(--accent)] underline decoration-[var(--accent)]/30 hover:decoration-[var(--accent)]"
        >
          FDA: {entry.actual_fda_action.title}
        </a>
      ) : (
        <p className="mt-1 text-xs text-[var(--text-tertiary)]">
          Awaiting FDA action
        </p>
      )}
      {leadMonths !== null ? (
        <p className="mt-1 text-xs text-[var(--text-secondary)]">
          Lead time: about {leadMonths} months ahead of FDA action
        </p>
      ) : null}
      {showMemorySources ? (
        <div className="mt-2 text-xs text-[var(--text-tertiary)]">
          <p>Stored as EverMemOS Foresight memory</p>
          <button
            type="button"
            onClick={() => onOpenForesightMemory?.(entry, foresightMemoryId)}
            className="mt-1 rounded bg-white/[0.04] px-1.5 py-0.5 font-mono text-[11px] text-[var(--text-tertiary)] transition hover:bg-white/[0.08] hover:text-[var(--text-primary)]"
          >
            {foresightMemoryId}
          </button>
        </div>
      ) : null}
    </div>
  );
}

export function PredictionScorecard({
  entries,
  loading,
  asOfQuarter = null,
  hiddenFutureCount = 0,
  showMemorySources = false,
  onOpenForesightMemory,
  demoStage = "baseline",
  presentationMode = "demo",
  receiptSummary = null,
  watchlistSummary = null,
}: PredictionScorecardProps) {
  const { activeEntries, archivedEntries } = splitScorecardEntries(
    entries,
    presentationMode,
  );
  const filteredOutPancreatitis = activeEntries.filter(
    (entry) => entry.prediction.adverse_event === "Pancreatitis",
  ).length;
  const displayEntries = activeEntries.filter(
    (entry) => entry.prediction.adverse_event !== "Pancreatitis",
  );
  const archivedDisplayEntries = archivedEntries.filter(
    (entry) => entry.prediction.adverse_event !== "Pancreatitis",
  );
  const ordered = orderEntries(displayEntries);
  const archivedOrdered = orderEntries(archivedDisplayEntries);
  const counts = countScorecardEntries(ordered);
  const validated = counts.validated;
  const pending = counts.pending;
  const early = counts.early;
  const resolved = ordered.length - pending;
  const primaryEntry = pickPrimaryEntry(ordered, demoStage, presentationMode);
  const primaryId = primaryEntry?.prediction.id ?? null;
  const secondaryEntries = ordered.filter(
    (entry) => entry.prediction.id !== primaryId,
  );
  const shouldCollapseSecondaryEntries =
    presentationMode === "demo" &&
    demoStage !== "analyst" &&
    validated >= 2 &&
    secondaryEntries.length > 1;
  const secondaryEntriesKey = secondaryEntries
    .map((entry) => entry.prediction.id)
    .join("|");
  const [showAllSecondaryEntries, setShowAllSecondaryEntries] = useState(false);

  useEffect(() => {
    setShowAllSecondaryEntries(false);
  }, [secondaryEntriesKey, shouldCollapseSecondaryEntries]);

  const visibleSecondaryEntries =
    shouldCollapseSecondaryEntries && !showAllSecondaryEntries
      ? secondaryEntries.slice(0, 1)
      : secondaryEntries;
  const hiddenSecondaryCount = Math.max(
    0,
    secondaryEntries.length - visibleSecondaryEntries.length,
  );

  return (
    <section className="rounded-xl border border-[var(--border)] bg-[var(--bg-panel)] p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="text-xs font-medium tracking-wide text-[var(--text-tertiary)]">
            Prediction Scorecard
          </h3>
          <p className="mt-1 text-xs leading-relaxed text-[var(--text-secondary)]">
            {stageSummary({
              presentationMode,
              demoStage,
              validated,
              pending,
              early,
              primaryEntry,
              receiptSummary,
              watchlistSummary,
            })}
          </p>
        </div>
        {asOfQuarter ? (
          <span className="font-mono text-xs text-[var(--text-secondary)]">
            As of {asOfQuarter}
          </span>
        ) : null}
      </div>

      {loading ? (
        <div className="mt-3 h-24 animate-pulse rounded-lg bg-[var(--bg-card)]" />
      ) : null}

      {!loading && displayEntries.length === 0 ? (
        <p className="mt-3 text-sm text-[var(--text-secondary)]">
          No predictions yet. They appear as higher-risk signals emerge.
        </p>
      ) : null}

      {!loading && hiddenFutureCount > 0 ? (
        <p className="mt-3 rounded-md bg-[var(--bg-card)] px-2.5 py-1.5 text-xs text-[var(--text-secondary)]">
          {hiddenFutureCount} later prediction
          {hiddenFutureCount === 1 ? "" : "s"} hidden by the selected quarter.
        </p>
      ) : null}

      {!loading && primaryEntry ? (
        <div className="mt-3 rounded-[1.2rem] border border-[var(--accent-border)] bg-[linear-gradient(145deg,rgba(212,149,106,0.16),rgba(26,26,30,0.95))] p-4">
          <div className="flex flex-wrap items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.18em]">
            <span className="rounded-full border border-[var(--accent-border)] bg-[var(--accent-dim)] px-2.5 py-1 text-[var(--accent)]">
              {demoStage === "validation" ? "Primary receipt" : "Lead receipt"}
            </span>
            <span className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[var(--text-secondary)]">
              {scoreLine(validated, pending, early, resolved)}
            </span>
          </div>
          <div className="mt-3">
            <EntryCard
              entry={primaryEntry}
              showMemorySources={showMemorySources}
              onOpenForesightMemory={onOpenForesightMemory}
            />
          </div>
        </div>
      ) : null}

      {!loading && visibleSecondaryEntries.length > 0 ? (
        <div className="mt-3 space-y-2">
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-tertiary)]">
            {demoStage === "validation"
              ? "Additional tracked outcomes"
              : "Also tracked"}
          </p>
          {visibleSecondaryEntries.map((entry) => (
            <EntryCard
              key={entry.prediction.id}
              entry={entry}
              showMemorySources={showMemorySources}
              onOpenForesightMemory={onOpenForesightMemory}
              subdued={demoStage === "validation"}
            />
          ))}
          {shouldCollapseSecondaryEntries ? (
            <button
              type="button"
              onClick={() =>
                setShowAllSecondaryEntries((current) => !current)
              }
              className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--text-secondary)] transition hover:bg-white/[0.08] hover:text-[var(--text-primary)]"
            >
              {showAllSecondaryEntries
                ? "Show less"
                : `Click for more (${hiddenSecondaryCount})`}
            </button>
          ) : null}
        </div>
      ) : null}

      {!loading &&
      presentationMode === "demo" &&
      demoStage === "analyst" &&
      archivedOrdered.length > 0 ? (
        <div className="mt-3 space-y-2">
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-tertiary)]">
            Not pursued
          </p>
          <p className="text-xs text-[var(--text-tertiary)]">
            {archivedOrdered.length} archived receipt horizon
            {archivedOrdered.length === 1 ? "" : "s"} remain available for
            analyst review and stay hidden from the primary demo list.
          </p>
          {archivedOrdered.map((entry) => (
            <EntryCard
              key={entry.prediction.id}
              entry={entry}
              showMemorySources={showMemorySources}
              onOpenForesightMemory={onOpenForesightMemory}
              subdued
              archived
              resultLabel="NOT PURSUED"
            />
          ))}
        </div>
      ) : null}

      {!loading && ordered.length > 0 ? (
        <>
          {filteredOutPancreatitis > 0 ? (
            <p className="mt-3 text-xs text-[var(--text-tertiary)]">
              Filtered: Pancreatitis prediction excluded (already on label at
              prediction time).
            </p>
          ) : null}
          <p className="mt-2 text-xs text-[var(--text-tertiary)]">
            Stage-specific framing controls the emphasis, but the underlying
            scorecard entries remain unchanged.
          </p>
        </>
      ) : null}
    </section>
  );
}
