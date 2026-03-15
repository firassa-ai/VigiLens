import type { CatalogPreviewResponse } from "../types/shared";

export interface MonitoringOptions {
  baselineQuarters: number;
  maxReports: number;
  preferCached: boolean;
}

interface DrugPreviewPanelProps {
  preview: CatalogPreviewResponse | null;
  candidateName: string | null;
  options: MonitoringOptions;
  loading?: boolean;
  error?: string | null;
  onboarding?: boolean;
  onboardingMessage?: string | null;
  onChangeOptions: (options: MonitoringOptions) => void;
  onStartMonitoring: () => void;
  onOpenCasefile: (drugId: string) => void;
}

const SCAN_DEPTHS = [
  { label: "Fast scan", value: 500 },
  { label: "Standard", value: 1500 },
  { label: "Deep", value: 5000 },
] as const;

export function DrugPreviewPanel({
  preview,
  candidateName,
  options,
  loading = false,
  error = null,
  onboarding = false,
  onboardingMessage = null,
  onChangeOptions,
  onStartMonitoring,
  onOpenCasefile,
}: DrugPreviewPanelProps) {
  const faersCountLabel =
    preview?.faers_report_count == null
      ? "Count unavailable before monitoring"
      : `${preview.faers_report_count.toLocaleString("en-US")} ${preview.faers_report_count_is_estimate ? "estimated" : "tracked"} reports`;

  return (
    <aside className="rounded-[1.5rem] border border-[var(--border)] bg-[linear-gradient(160deg,rgba(20,18,16,0.98),rgba(29,22,18,0.94))] p-4 shadow-[0_16px_50px_rgba(0,0,0,0.24)]">
      <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-[var(--text-tertiary)]">
        Drug Preview
      </p>

      {loading ? <div className="mt-4 h-[420px] animate-pulse rounded-[1.1rem] bg-[var(--bg-card)]" /> : null}
      {!loading && error ? (
        <div className="mt-4 rounded-[1rem] border border-red-500/25 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          {error}
        </div>
      ) : null}
      {!loading && !error && !preview ? (
        <div className="mt-4 rounded-[1.1rem] border border-dashed border-white/10 bg-black/15 px-4 py-6 text-sm leading-relaxed text-[var(--text-secondary)]">
          Select a result to inspect its labels, scan depth, and monitoring options before opening the casefile.
        </div>
      ) : null}

      {!loading && !error && preview ? (
        <div className="mt-4 space-y-4">
          <div>
            <p className="font-display text-2xl text-[var(--text-primary)]">{preview.generic_name}</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {preview.brand_names.map((brand) => (
                <span
                  key={brand}
                  className="rounded-full border border-white/10 bg-white/[0.05] px-2.5 py-1 text-[11px] text-[var(--text-secondary)]"
                >
                  {brand}
                </span>
              ))}
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-[1rem] border border-white/10 bg-black/15 p-3">
              <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--text-tertiary)]">
                Status
              </p>
              <p className="mt-2 text-sm text-[var(--text-primary)]">
                {preview.tracked ? "Already tracked" : preview.faers_available ? "Ready to monitor" : "No FAERS match yet"}
              </p>
            </div>
            <div className="rounded-[1rem] border border-white/10 bg-black/15 p-3">
              <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--text-tertiary)]">
                Label
              </p>
              <p className="mt-2 text-sm text-[var(--text-primary)]">
                {preview.dailymed_title ? "DailyMed label found" : "No label metadata found"}
              </p>
            </div>
          </div>

          <div className="rounded-[1.1rem] border border-white/10 bg-black/15 p-4">
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--text-tertiary)]">
              FAERS depth
            </p>
            <p className="mt-2 text-sm text-[var(--text-primary)]">{faersCountLabel}</p>
            {preview.faers_report_count_is_estimate ? (
              <p className="mt-2 text-xs leading-relaxed text-[var(--text-secondary)]">
                Estimate from openFDA search volume before target-only filtering, dedupe, and local seeding.
              </p>
            ) : null}
          </div>

          <div className="rounded-[1.1rem] border border-white/10 bg-black/15 p-4">
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--text-tertiary)]">
              Latest label metadata
            </p>
            <p className="mt-2 text-sm leading-relaxed text-[var(--text-primary)]">
              {preview.dailymed_title ?? "No DailyMed title returned for this candidate."}
            </p>
            {preview.dailymed_published_date ? (
              <p className="mt-2 text-xs text-[var(--text-secondary)]">
                Last published: {preview.dailymed_published_date}
              </p>
            ) : null}
          </div>

          <div className="rounded-[1.1rem] border border-white/10 bg-black/15 p-4">
            <div className="flex items-center justify-between gap-3">
              <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[var(--text-tertiary)]">
                Advanced options
              </p>
              <p className="text-[10px] uppercase tracking-[0.18em] text-[var(--text-tertiary)]">
                API key recommended for deep live pulls
              </p>
            </div>

            <div className="mt-4 space-y-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">
                  Scan depth
                </p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {SCAN_DEPTHS.map((depth) => {
                    const active = options.maxReports === depth.value;
                    return (
                      <button
                        key={depth.value}
                        type="button"
                        onClick={() => onChangeOptions({ ...options, maxReports: depth.value })}
                        className={`rounded-full border px-3 py-2 text-xs font-semibold uppercase tracking-[0.18em] transition ${
                          active
                            ? "border-[var(--accent-border)] bg-[var(--accent-dim)] text-[var(--accent)]"
                            : "border-white/10 bg-white/[0.04] text-[var(--text-secondary)] hover:bg-white/[0.08] hover:text-[var(--text-primary)]"
                        }`}
                      >
                        {depth.label}
                      </button>
                    );
                  })}
                </div>
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <label className="space-y-2 text-sm text-[var(--text-secondary)]">
                  <span className="text-xs font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">
                    Baseline quarters
                  </span>
                  <select
                    value={String(options.baselineQuarters)}
                    onChange={(event) =>
                      onChangeOptions({
                        ...options,
                        baselineQuarters: Number(event.target.value),
                      })
                    }
                    className="w-full rounded-[0.9rem] border border-white/10 bg-black/20 px-3 py-3 text-sm text-[var(--text-primary)]"
                  >
                    <option value="4">4 quarters</option>
                    <option value="8">8 quarters</option>
                  </select>
                </label>

                <label className="space-y-2 text-sm text-[var(--text-secondary)]">
                  <span className="text-xs font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">
                    Prefer cached
                  </span>
                  <button
                    type="button"
                    onClick={() => onChangeOptions({ ...options, preferCached: !options.preferCached })}
                    className={`flex w-full items-center justify-between rounded-[0.9rem] border px-3 py-3 text-sm transition ${
                      options.preferCached
                        ? "border-[var(--accent-border)] bg-[var(--accent-dim)] text-[var(--accent)]"
                        : "border-white/10 bg-black/20 text-[var(--text-secondary)]"
                    }`}
                  >
                    <span>{options.preferCached ? "Enabled" : "Disabled"}</span>
                    <span className="text-[11px] uppercase tracking-[0.18em]">{options.preferCached ? "Cache" : "Live"}</span>
                  </button>
                </label>
              </div>
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            {preview.tracked && preview.tracked_drug_id ? (
              <button
                type="button"
                onClick={() => onOpenCasefile(preview.tracked_drug_id as string)}
                className="rounded-full border border-[var(--accent-border)] bg-[var(--accent-dim)] px-4 py-3 text-xs font-semibold uppercase tracking-[0.18em] text-[var(--accent)] transition hover:bg-[rgba(214,160,110,0.18)]"
              >
                Open Casefile
              </button>
            ) : (
              <button
                type="button"
                onClick={onStartMonitoring}
                disabled={onboarding || !preview.faers_available}
                className="rounded-full border border-[var(--accent-border)] bg-[var(--accent-dim)] px-4 py-3 text-xs font-semibold uppercase tracking-[0.18em] text-[var(--accent)] transition hover:bg-[rgba(214,160,110,0.18)] disabled:cursor-not-allowed disabled:opacity-60"
              >
                {onboarding ? "Starting monitoring" : "Start Monitoring"}
              </button>
            )}
            {candidateName ? (
              <span className="inline-flex items-center rounded-full border border-white/10 bg-white/[0.04] px-3 py-3 text-[11px] uppercase tracking-[0.18em] text-[var(--text-tertiary)]">
                Candidate: {candidateName}
              </span>
            ) : null}
          </div>

          {onboardingMessage ? (
            <p className="text-sm leading-relaxed text-[var(--text-secondary)]">{onboardingMessage}</p>
          ) : null}
        </div>
      ) : null}
    </aside>
  );
}
