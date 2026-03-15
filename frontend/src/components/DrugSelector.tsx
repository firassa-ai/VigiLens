import { useState } from "react";

import type { Drug } from "../types/shared";

export interface DrugSelectorProps {
  drugs: Drug[];
  selectedDrugId: string;
  onSelect: (drugId: string) => void;
  loading?: boolean;
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

export function DrugSelector({
  drugs,
  selectedDrugId,
  onSelect,
  loading = false,
}: DrugSelectorProps) {
  const [expandedBrands, setExpandedBrands] = useState<Record<string, boolean>>({});

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-panel)] p-4">
      <h3 className="mb-3 text-xs font-medium tracking-wide text-[var(--text-tertiary)]">
        Tracked Casefiles
      </h3>
      {loading ? <div className="h-20 animate-pulse rounded-lg bg-[var(--bg-card)]" /> : null}
      {!loading && drugs.length === 0 ? (
        <p className="text-sm text-[var(--text-secondary)]">No tracked drugs yet.</p>
      ) : null}
      <div className="space-y-1.5">
        {drugs.map((drug) => {
          const selected = drug.id === selectedDrugId;
          const expanded = Boolean(expandedBrands[drug.id]);
          const { label, hiddenCount } = getBrandPreview(drug.brand_names, expanded);
          return (
            <article
              key={drug.id}
              className={`w-full rounded-lg px-3 py-2.5 text-left transition ${
                selected
                  ? "bg-[var(--accent-dim)] ring-1 ring-[var(--accent-border)]"
                  : "hover:bg-white/[0.03]"
              }`}
            >
              <button
                type="button"
                onClick={() => onSelect(drug.id)}
                className="w-full text-left"
              >
                <div className="flex items-center justify-between gap-2">
                  <p className={`text-sm font-medium ${selected ? "text-[var(--accent)]" : "text-[var(--text-primary)]"}`}>
                    {drug.generic_name}
                  </p>
                  <span className="font-mono text-[11px] text-[var(--text-tertiary)]">
                    {drug.quarters_loaded.length}q
                  </span>
                </div>
                <p className="mt-0.5 text-xs leading-relaxed text-[var(--text-secondary)]">
                  {label}
                </p>
                {drug.next_quarter ? (
                  <p className="mt-0.5 text-xs text-[var(--text-tertiary)]">
                    Next: {drug.next_quarter}
                  </p>
                ) : null}
              </button>
              {hiddenCount > 0 ? (
                <button
                  type="button"
                  onClick={() =>
                    setExpandedBrands((current) => ({
                      ...current,
                      [drug.id]: !current[drug.id],
                    }))
                  }
                  className={`mt-1 text-[11px] font-medium uppercase tracking-[0.16em] transition ${
                    selected ? "text-[var(--accent)] hover:text-[var(--text-primary)]" : "text-[var(--accent)] hover:text-[var(--text-primary)]"
                  }`}
                >
                  {expanded ? "Show less" : `+${hiddenCount} more`}
                </button>
              ) : null}
            </article>
          );
        })}
      </div>
    </div>
  );
}
