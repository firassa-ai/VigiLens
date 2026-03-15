import type { TrackingJob } from "../types/shared";

interface TrackingJobStatusDetailsProps {
  job: TrackingJob;
}

function asNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

export function TrackingJobStatusDetails({ job }: TrackingJobStatusDetailsProps) {
  const details = job.details_json ?? {};
  const statusMessage = asString(details.status_message);
  const windowIndex = asNumber(details.window_index);
  const windowTotal = asNumber(details.window_total);
  const pagesFetched = asNumber(details.pages_fetched);
  const matchedReports = asNumber(details.matched_reports);
  const providerRowsSeen = asNumber(details.provider_rows_seen);

  const metrics: Array<{ label: string; value: string }> = [];
  if (windowIndex !== null && windowTotal !== null) {
    metrics.push({ label: "Month", value: `${windowIndex}/${windowTotal}` });
  }
  if (pagesFetched !== null) {
    metrics.push({ label: "Pages", value: pagesFetched.toLocaleString("en-US") });
  }
  if (matchedReports !== null) {
    metrics.push({ label: "Matched", value: matchedReports.toLocaleString("en-US") });
  }
  if (providerRowsSeen !== null) {
    metrics.push({ label: "Rows seen", value: providerRowsSeen.toLocaleString("en-US") });
  }

  if (!statusMessage && metrics.length === 0) {
    return null;
  }

  return (
    <div className="mt-3 rounded-[1rem] border border-white/10 bg-black/15 px-3 py-2.5">
      {statusMessage ? (
        <p className="text-xs leading-relaxed text-[var(--text-secondary)]">{statusMessage}</p>
      ) : null}
      {metrics.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-2">
          {metrics.map((metric) => (
            <span
              key={`${metric.label}:${metric.value}`}
              className="rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--text-tertiary)]"
            >
              {metric.label}: {metric.value}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}
