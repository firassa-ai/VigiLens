import { useState } from "react";

import type { Drug } from "../types/shared";

interface TrackedDrugListProps {
  drugs: Drug[];
  selectedDrugId: string | null;
  loading?: boolean;
  deletingDrugId?: string | null;
  error?: string | null;
  onOpen: (drugId: string) => void;
  onDelete: (drugId: string) => Promise<boolean>;
}

const DEFAULT_BRAND_LIMIT = 2;

function getBrandPreview(brandNames: string[], expanded: boolean) {
  if (brandNames.length === 0) {
    return {
      label: "No brands recorded",
      hiddenCount: 0,
    };
  }

  const visible = expanded ? brandNames : brandNames.slice(0, DEFAULT_BRAND_LIMIT);
  return {
    label: visible.join(" / "),
    hiddenCount: Math.max(0, brandNames.length - DEFAULT_BRAND_LIMIT),
  };
}

export function TrackedDrugList({
  drugs,
  selectedDrugId,
  loading = false,
  deletingDrugId = null,
  error = null,
  onOpen,
  onDelete,
}: TrackedDrugListProps) {
  const [expandedBrands, setExpandedBrands] = useState<Record<string, boolean>>({});
  const [confirmDeleteDrugId, setConfirmDeleteDrugId] = useState<string | null>(null);

  return (
    <section className="rounded-[1.5rem] border border-[var(--border)] bg-[var(--bg-panel)] p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-[var(--text-tertiary)]">
            Tracked Drugs
          </p>
          <h2 className="mt-1 font-display text-xl text-[var(--text-primary)]">Current portfolio</h2>
        </div>
        <span className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-[11px] text-[var(--text-secondary)]">
          {drugs.length}
        </span>
      </div>

      {loading ? <div className="mt-4 h-52 animate-pulse rounded-[1.1rem] bg-[var(--bg-card)]" /> : null}

      {!loading && drugs.length === 0 ? (
        <p className="mt-4 text-sm leading-relaxed text-[var(--text-secondary)]">
          No tracked drugs yet. The built-in competition demo seeds semaglutide for validated receipts and
          minoxidil for proof-backed generalization. You can also preview a new candidate here and start a
          custom casefile.
        </p>
      ) : null}

      {error ? (
        <div className="mt-4 rounded-[1rem] border border-red-500/25 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          {error}
        </div>
      ) : null}

      <div className="mt-4 space-y-2">
        {drugs.map((drug) => {
          const selected = drug.id === selectedDrugId;
          const expanded = Boolean(expandedBrands[drug.id]);
          const { label, hiddenCount } = getBrandPreview(drug.brand_names, expanded);
          const confirmingDelete = confirmDeleteDrugId === drug.id;
          const deleting = deletingDrugId === drug.id;

          return (
            <article
              key={drug.id}
              className={`rounded-[1.1rem] border px-4 py-3 transition ${
                selected
                  ? "border-[var(--accent-border)] bg-[var(--accent-dim)]"
                  : "border-white/10 bg-black/15 hover:bg-white/[0.04]"
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <button
                    type="button"
                    onClick={() => onOpen(drug.id)}
                    className="w-full text-left"
                  >
                    <p
                      className={`text-sm font-semibold ${
                        selected ? "text-[var(--accent)]" : "text-[var(--text-primary)]"
                      }`}
                    >
                      {drug.generic_name}
                    </p>
                  </button>
                  <p className="mt-1 text-xs leading-relaxed text-[var(--text-secondary)]">{label}</p>
                  {hiddenCount > 0 ? (
                    <button
                      type="button"
                      onClick={() =>
                        setExpandedBrands((current) => ({
                          ...current,
                          [drug.id]: !current[drug.id],
                        }))
                      }
                      className="mt-1 text-[11px] font-medium uppercase tracking-[0.16em] text-[var(--accent)] transition hover:text-[var(--text-primary)]"
                    >
                      {expanded ? "Show less" : `+${hiddenCount} more`}
                    </button>
                  ) : null}
                </div>

                <div className="flex shrink-0 flex-col items-end gap-2">
                  <span className="font-mono text-[11px] text-[var(--text-tertiary)]">
                    {drug.total_reports.toLocaleString("en-US")}
                  </span>
                  <button
                    type="button"
                    onClick={() =>
                      setConfirmDeleteDrugId((current) => (current === drug.id ? null : drug.id))
                    }
                    disabled={deleting}
                    className="rounded-full border border-red-500/20 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-red-200 transition hover:border-red-400/40 hover:text-red-100 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {deleting ? "Deleting" : "Delete"}
                  </button>
                </div>
              </div>

              {confirmingDelete ? (
                <div className="mt-3 rounded-[0.95rem] border border-red-500/20 bg-red-500/10 px-3 py-3">
                  <p className="text-sm text-red-100">
                    Remove <span className="font-semibold">{drug.generic_name}</span> from tracked casefiles?
                  </p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => setConfirmDeleteDrugId(null)}
                      disabled={deleting}
                      className="rounded-full border border-white/10 px-3 py-1.5 text-[11px] font-medium uppercase tracking-[0.16em] text-[var(--text-secondary)] transition hover:text-[var(--text-primary)] disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      onClick={async () => {
                        const deleted = await onDelete(drug.id);
                        if (deleted) {
                          setConfirmDeleteDrugId((current) => (current === drug.id ? null : current));
                        }
                      }}
                      disabled={deleting}
                      className="rounded-full border border-red-500/25 bg-red-500/15 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.16em] text-red-100 transition hover:border-red-400/45 hover:bg-red-500/20 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {deleting ? "Removing" : "Confirm delete"}
                    </button>
                  </div>
                </div>
              ) : null}
            </article>
          );
        })}
      </div>
    </section>
  );
}
