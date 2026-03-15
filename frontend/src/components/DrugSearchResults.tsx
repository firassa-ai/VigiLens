import type { CatalogSearchResult } from "../types/shared";

interface DrugSearchResultsProps {
  results: CatalogSearchResult[];
  query: string;
  selectedGenericName: string | null;
  loading?: boolean;
  error?: string | null;
  onboarding?: boolean;
  onSelect: (genericName: string) => void;
  onQuickStart: (genericName: string) => void | Promise<void>;
  onOpenCasefile: (drugId: string) => void;
}

function badgeLabel(source: CatalogSearchResult["sources"][number]): string {
  if (source === "dailymed") {
    return "DailyMed";
  }
  if (source === "faers") {
    return "FAERS";
  }
  return "Tracked";
}

export function DrugSearchResults({
  results,
  query,
  selectedGenericName,
  loading = false,
  error = null,
  onboarding = false,
  onSelect,
  onQuickStart,
  onOpenCasefile,
}: DrugSearchResultsProps) {
  return (
    <section className="rounded-[1.5rem] border border-[var(--border)] bg-[var(--bg-panel)] p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-[var(--text-tertiary)]">
            Search Results
          </p>
          <h2 className="mt-1 font-display text-xl text-[var(--text-primary)]">
            {query.trim().length >= 2 ? `Results for "${query.trim()}"` : "Start with a drug name"}
          </h2>
        </div>
      </div>

      {loading ? <div className="mt-4 h-80 animate-pulse rounded-[1.1rem] bg-[var(--bg-card)]" /> : null}
      {!loading && error ? (
        <div className="mt-4 rounded-[1rem] border border-red-500/25 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          {error}
        </div>
      ) : null}
      {!loading && !error && query.trim().length < 2 ? (
        <p className="mt-4 text-sm leading-relaxed text-[var(--text-secondary)]">
          Try a generic or brand name like <span className="text-[var(--text-primary)]">clozapine</span>,
          <span className="text-[var(--text-primary)]"> Ozempic</span>, or
          <span className="text-[var(--text-primary)]"> Wegovy</span>.
        </p>
      ) : null}
      {!loading && !error && query.trim().length >= 2 && results.length === 0 ? (
        <p className="mt-4 text-sm leading-relaxed text-[var(--text-secondary)]">
          No catalog matches yet. Try a broader brand or generic spelling.
        </p>
      ) : null}

      <div className="mt-4 grid gap-3 xl:grid-cols-2">
        {results.map((result) => {
          const selected = result.generic_name === selectedGenericName;
          return (
            <article
              key={`${result.tracked_drug_id ?? "candidate"}:${result.generic_name}`}
              className={`rounded-[1.2rem] border p-4 transition ${
                selected
                  ? "border-[var(--accent-border)] bg-[rgba(214,160,110,0.08)]"
                  : "border-white/10 bg-black/15 hover:bg-white/[0.04]"
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <button
                    type="button"
                    onClick={() => onSelect(result.generic_name)}
                    className="text-left"
                  >
                    <p className="font-display text-xl leading-tight text-[var(--text-primary)]">{result.generic_name}</p>
                  </button>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {result.brand_names.slice(0, 4).map((brand) => (
                      <span
                        key={brand}
                        className="rounded-full border border-white/10 bg-white/[0.05] px-2.5 py-1 text-[11px] text-[var(--text-secondary)]"
                      >
                        {brand}
                      </span>
                    ))}
                  </div>
                </div>

                <div className="flex flex-col items-end gap-2">
                  <span
                    className={`rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] ${
                      result.tracked
                        ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-200"
                        : "border-white/10 bg-white/[0.04] text-[var(--text-secondary)]"
                    }`}
                  >
                    {result.tracked ? "Tracked" : "Not tracked"}
                  </span>
                  {result.label_available ? (
                    <span className="rounded-full border border-[var(--accent-border)] bg-[var(--accent-dim)] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--accent)]">
                      Label available
                    </span>
                  ) : null}
                </div>
              </div>

              <div className="mt-4 flex flex-wrap gap-2">
                {result.sources.map((source) => (
                  <span
                    key={`${result.generic_name}:${source}`}
                    className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]"
                  >
                    {badgeLabel(source)}
                  </span>
                ))}
              </div>

              <div className="mt-4 flex flex-wrap gap-2">
                {result.tracked && result.tracked_drug_id ? (
                  <button
                    type="button"
                    onClick={() => onOpenCasefile(result.tracked_drug_id as string)}
                    className="rounded-full border border-[var(--accent-border)] bg-[var(--accent-dim)] px-3 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-[var(--accent)] transition hover:bg-[rgba(214,160,110,0.18)]"
                  >
                    Open Casefile
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => {
                      void onQuickStart(result.generic_name);
                    }}
                    disabled={onboarding}
                    className="rounded-full border border-[var(--accent-border)] bg-[var(--accent-dim)] px-3 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-[var(--accent)] transition hover:bg-[rgba(214,160,110,0.18)] disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {onboarding ? "Starting..." : "Start Monitoring"}
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => onSelect(result.generic_name)}
                  className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)] transition hover:bg-white/[0.08] hover:text-[var(--text-primary)]"
                >
                  Preview
                </button>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
