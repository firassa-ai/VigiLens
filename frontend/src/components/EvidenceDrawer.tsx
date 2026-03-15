import { useEffect, useMemo, useState } from "react";

import { getEvidence } from "../api/client";
import type { FAERSReport } from "../types/shared";

export interface EvidenceDrawerProps {
  open: boolean;
  reportId: string | null;
  initialReport?: FAERSReport | null;
  onClose: () => void;
  onLoaded?: (report: FAERSReport | null) => void;
}

function formatAge(value: number | null): string {
  if (value === null) {
    return "Unknown";
  }
  return `${value.toFixed(1)} years`;
}

export function EvidenceDrawer({
  open,
  reportId,
  initialReport = null,
  onClose,
  onLoaded,
}: EvidenceDrawerProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<FAERSReport | null>(null);

  useEffect(() => {
    if (!open || !reportId) {
      setReport(null);
      setError(null);
      setLoading(false);
      onLoaded?.(null);
      return;
    }

    if (initialReport && initialReport.safetyreportid === reportId) {
      setReport(initialReport);
      setError(null);
      setLoading(false);
      onLoaded?.(initialReport);
      return;
    }

    const controller = new AbortController();
    setReport(null);
    setLoading(true);
    setError(null);

    getEvidence(reportId, controller.signal)
      .then((nextReport) => {
        setReport(nextReport);
        onLoaded?.(nextReport);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load evidence report");
        onLoaded?.(null);
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      });

    return () => {
      controller.abort();
    };
  }, [initialReport, open, reportId, onLoaded]);

  const panelClass = useMemo(() => {
    return [
      "fixed right-0 top-0 z-40 h-screen w-full max-w-[520px] border-l border-[var(--border)]",
      "bg-[var(--bg-root)]/[0.97] p-6 shadow-2xl backdrop-blur-xl transition-transform duration-300",
      open ? "translate-x-0" : "translate-x-full",
    ].join(" ");
  }, [open]);

  return (
    <>
      <div
        className={`fixed inset-0 z-30 bg-black/50 transition-opacity duration-300 ${open ? "opacity-100" : "pointer-events-none opacity-0"}`}
        onClick={onClose}
      />
      <aside className={panelClass} aria-hidden={!open}>
        <div className="mb-6 flex items-start justify-between gap-3">
          <div>
            <p className="text-xs font-medium text-[var(--text-tertiary)]">Evidence Report</p>
            <h3 className="mt-1 font-display text-xl text-[var(--text-primary)]">
              {reportId ?? "No report selected"}
            </h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md bg-white/[0.04] px-3 py-1.5 text-xs font-medium text-[var(--text-secondary)] transition hover:bg-white/[0.08]"
          >
            Close
          </button>
        </div>

        {loading ? <p className="text-sm text-[var(--text-secondary)]">Loading\u2026</p> : null}
        {error ? (
          <p className="rounded-lg border border-red-500/20 bg-[var(--danger-dim)] p-3 text-sm text-red-300">{error}</p>
        ) : null}

        {!loading && !error && report ? (
          <div className="space-y-5 text-sm text-[var(--text-secondary)]">
            <div className="grid grid-cols-2 gap-3 rounded-xl bg-[var(--bg-panel)] p-4">
              <div>
                <p className="text-xs font-medium text-[var(--text-tertiary)]">Received</p>
                <p className="mt-0.5 text-[var(--text-primary)]">{report.receivedate}</p>
              </div>
              <div>
                <p className="text-xs font-medium text-[var(--text-tertiary)]">Version</p>
                <p className="mt-0.5 text-[var(--text-primary)]">{report.version}</p>
              </div>
              <div>
                <p className="text-xs font-medium text-[var(--text-tertiary)]">Sex</p>
                <p className="mt-0.5 text-[var(--text-primary)]">{report.patient_sex}</p>
              </div>
              <div>
                <p className="text-xs font-medium text-[var(--text-tertiary)]">Age</p>
                <p className="mt-0.5 text-[var(--text-primary)]">{formatAge(report.patient_age)}</p>
              </div>
              <div>
                <p className="text-xs font-medium text-[var(--text-tertiary)]">Serious</p>
                <p className="mt-0.5 text-[var(--text-primary)]">{report.serious ? "Yes" : "No"}</p>
              </div>
              <div>
                <p className="text-xs font-medium text-[var(--text-tertiary)]">Outcomes</p>
                <p className="mt-0.5 text-[var(--text-primary)]">{report.outcomes.join(", ") || "None"}</p>
              </div>
            </div>

            <section>
              <h4 className="mb-2 font-display text-base text-[var(--text-primary)]">Suspect Drugs</h4>
              <p>{report.suspect_drugs.join(", ") || "None"}</p>
            </section>

            <section>
              <h4 className="mb-2 font-display text-base text-[var(--text-primary)]">Concomitant Drugs</h4>
              <p>{report.concomitant_drugs.join(", ") || "None"}</p>
            </section>

            <section>
              <h4 className="mb-2 font-display text-base text-[var(--text-primary)]">Reactions</h4>
              <div className="flex flex-wrap gap-1.5">
                {report.reactions.length === 0 ? <span>None</span> : null}
                {report.reactions.map((reaction) => (
                  <span key={reaction} className="rounded-md bg-[var(--accent-dim)] px-2 py-1 text-xs text-[var(--accent)]">
                    {reaction}
                  </span>
                ))}
              </div>
            </section>
          </div>
        ) : null}
      </aside>
    </>
  );
}
