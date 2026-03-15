import { useEffect, useState } from "react";

interface DrugSearchBarProps {
  initialValue: string;
  loading?: boolean;
  onDebouncedChange: (value: string) => void;
  onSubmit: (value: string) => void;
}

export function DrugSearchBar({
  initialValue,
  loading = false,
  onDebouncedChange,
  onSubmit,
}: DrugSearchBarProps) {
  const [value, setValue] = useState(initialValue);

  useEffect(() => {
    setValue(initialValue);
  }, [initialValue]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      onDebouncedChange(value);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [onDebouncedChange, value]);

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit(value);
      }}
      className="rounded-[1.75rem] border border-[var(--border)] bg-[linear-gradient(135deg,rgba(22,20,18,0.98),rgba(40,28,21,0.92))] p-5 shadow-[0_24px_80px_rgba(0,0,0,0.22)]"
    >
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="max-w-2xl">
          <p className="text-[11px] font-semibold uppercase tracking-[0.26em] text-[var(--text-tertiary)]">
            Discover
          </p>
          <h1 className="mt-2 font-display text-[clamp(2.1rem,4vw,4rem)] leading-[0.95] text-[var(--text-primary)]">
            Search any drug by generic or brand name.
          </h1>
        </div>
        <p className="max-w-sm text-sm leading-relaxed text-[var(--text-secondary)]">
          Search the tracked portfolio first, enrich with DailyMed labels, then preview and start monitoring.
        </p>
      </div>

      <div className="mt-5 flex flex-col gap-3 md:flex-row">
        <label className="group relative flex-1">
          <span className="sr-only">Search any drug by generic or brand name</span>
          <input
            type="search"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder="clozapine, Ozempic, Wegovy"
            className="w-full rounded-[1.2rem] border border-white/10 bg-black/20 px-4 py-4 text-base text-[var(--text-primary)] outline-none transition placeholder:text-[var(--text-tertiary)] focus:border-[var(--accent-border)] focus:bg-black/30"
          />
          <div className="pointer-events-none absolute inset-y-0 right-4 flex items-center text-[11px] uppercase tracking-[0.2em] text-[var(--text-tertiary)]">
            Enter
          </div>
        </label>
        <button
          type="submit"
          className="rounded-[1.1rem] border border-[var(--accent-border)] bg-[var(--accent-dim)] px-5 py-4 text-xs font-semibold uppercase tracking-[0.22em] text-[var(--accent)] transition hover:bg-[rgba(214,160,110,0.18)] disabled:opacity-70"
          disabled={loading}
        >
          {loading ? "Searching" : "Search"}
        </button>
      </div>
    </form>
  );
}
