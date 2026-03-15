import { useMemo, useState } from "react";
import {
  Area,
  Brush,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { FDAAction, ScorecardEntry, SignalPoint } from "../types/shared";

export interface SignalTimelineProps {
  points: SignalPoint[];
  fdaActions: FDAAction[];
  predictionEntries?: ScorecardEntry[];
  selectedEvents: string[];
  onToggleEvent: (event: string) => void;
  activeQuarter: string;
  reinterpretationMarkers?: Array<{ quarter: string; reportId: string }>;
}

const lineColors = [
  "#d4956a",
  "#6ba5d4",
  "#7dd47a",
  "#c77dba",
  "#e07070",
  "#5ec4b6",
  "#e0c060",
  "#8b80d4",
  "#d47090",
  "#8a9bb0",
];

type ChartRow = {
  quarter: string;
  [event: string]: number | string | null;
};

function dateToQuarter(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  const quarter = Math.floor(date.getUTCMonth() / 3) + 1;
  return `${date.getUTCFullYear()}-Q${quarter}`;
}

export function quarterSortValue(quarter: string): number {
  const match = /^(\d{4})-Q([1-4])$/.exec(quarter);
  if (!match) {
    return -1;
  }
  return Number(match[1]) * 10 + Number(match[2]);
}

export function quarterIsAtOrBefore(candidate: string, active: string): boolean {
  return quarterSortValue(candidate) <= quarterSortValue(active);
}

export function filterVisibleTimelineMarkers(
  params: {
    fdaActions: FDAAction[];
    predictionEntries: ScorecardEntry[];
    activeQuarter: string;
  },
): { visibleFdaQuarters: string[]; visiblePredictionQuarters: string[] } {
  const { fdaActions, predictionEntries, activeQuarter } = params;
  const visibleFdaQuarters = fdaActions
    .map((action) => dateToQuarter(action.date))
    .filter((quarter): quarter is string => Boolean(quarter) && quarterIsAtOrBefore(quarter, activeQuarter));

  const visiblePredictionQuarters = predictionEntries
    .map((entry) => entry.prediction.created_at_quarter)
    .filter((quarter) => quarterIsAtOrBefore(quarter, activeQuarter));

  return {
    visibleFdaQuarters,
    visiblePredictionQuarters,
  };
}

function formatMaybe(value: number | null): string {
  if (value === null || Number.isNaN(value)) {
    return "-";
  }
  return value.toFixed(2);
}

export function SignalTimeline({
  points,
  fdaActions,
  predictionEntries = [],
  selectedEvents,
  onToggleEvent,
  activeQuarter,
  reinterpretationMarkers = [],
}: SignalTimelineProps) {
  const [brushRange, setBrushRange] = useState<{ startIndex: number; endIndex: number } | null>(null);

  const quarters = useMemo(() => {
    return Array.from(new Set(points.map((point) => point.quarter))).sort();
  }, [points]);

  const pointsByQuarterEvent = useMemo(() => {
    const out = new Map<string, SignalPoint>();
    for (const point of points) {
      out.set(`${point.quarter}::${point.adverse_event}`, point);
    }
    return out;
  }, [points]);

  const availableEvents = useMemo(() => {
    const latestQuarter = [...quarters].sort().at(-1);
    const latestPoints = latestQuarter
      ? points.filter((point) => point.quarter === latestQuarter)
      : points;

    return [...latestPoints]
      .sort((a, b) => {
        const aScore = a.ror_ci_lower ?? -1;
        const bScore = b.ror_ci_lower ?? -1;
        if (a.signal_detected !== b.signal_detected) {
          return Number(b.signal_detected) - Number(a.signal_detected);
        }
        if (aScore !== bScore) {
          return bScore - aScore;
        }
        return b.report_count - a.report_count;
      })
      .map((point) => point.adverse_event);
  }, [points, quarters]);

  const chartRows = useMemo(() => {
    const rows: ChartRow[] = quarters.map((quarter) => ({ quarter }));
    const rowByQuarter = new Map(rows.map((row) => [row.quarter, row]));

    for (const point of points) {
      if (!selectedEvents.includes(point.adverse_event)) {
        continue;
      }
      const row = rowByQuarter.get(point.quarter);
      if (!row) {
        continue;
      }
      row[point.adverse_event] = point.ror;
    }

    if (!brushRange) {
      return rows;
    }

    return rows.slice(brushRange.startIndex, brushRange.endIndex + 1);
  }, [points, quarters, selectedEvents, brushRange]);

  const markerLines = useMemo(() => {
    const visibleQuarters = new Set(chartRows.map((row) => String(row.quarter)));
    const counts = new Map<string, number>();
    for (const marker of reinterpretationMarkers) {
      if (!visibleQuarters.has(marker.quarter)) {
        continue;
      }
      counts.set(marker.quarter, (counts.get(marker.quarter) ?? 0) + 1);
    }
    return Array.from(counts.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .slice(0, 6)
      .map(([quarter, count]) => ({ quarter, count }));
  }, [chartRows, reinterpretationMarkers]);

  const ileusEmergence = useMemo(() => {
    const orderedIleus = points
      .filter((point) => point.adverse_event === "Ileus")
      .sort((a, b) => quarterSortValue(a.quarter) - quarterSortValue(b.quarter));

    let previouslyDetected = false;
    for (const point of orderedIleus) {
      if (!quarterIsAtOrBefore(point.quarter, activeQuarter)) {
        continue;
      }
      const detected = point.signal_detected && point.ror_ci_lower !== null && point.ror_ci_lower > 1;
      if (detected && !previouslyDetected) {
        return {
          quarter: point.quarter,
        };
      }
      previouslyDetected = detected;
    }
    return null;
  }, [activeQuarter, points]);

  const visibleFdaMarkers = useMemo(() => {
    if (!activeQuarter) {
      return [];
    }
    const { visibleFdaQuarters } = filterVisibleTimelineMarkers({
      fdaActions,
      predictionEntries,
      activeQuarter,
    });
    return fdaActions
      .map((action) => ({ ...action, quarter: dateToQuarter(action.date) }))
      .filter((action) => action.quarter && visibleFdaQuarters.includes(action.quarter));
  }, [activeQuarter, fdaActions, predictionEntries]);

  const visiblePredictionMarkers = useMemo(() => {
    if (!activeQuarter) {
      return [];
    }
    const { visiblePredictionQuarters } = filterVisibleTimelineMarkers({
      fdaActions,
      predictionEntries,
      activeQuarter,
    });
    return predictionEntries.filter((entry) =>
      visiblePredictionQuarters.includes(entry.prediction.created_at_quarter),
    );
  }, [activeQuarter, predictionEntries]);

  if (points.length === 0) {
    return (
      <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-panel)] p-5 lg:p-6">
        <h2 className="font-display text-xl text-[var(--text-primary)]">Signal Trajectory Field</h2>
        <p className="mt-3 text-sm text-[var(--text-secondary)]">
          No timeline data yet. Load the baseline or use the analyst workspace controls to ingest the first quarters.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-panel)] p-5 lg:p-6">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="font-display text-xl text-[var(--text-primary)]">Signal Trajectory Field</h2>
          <p className="mt-0.5 text-xs text-[var(--text-secondary)]">
            As of {activeQuarter}
          </p>
          <p className="mt-1 max-w-2xl text-xs leading-relaxed text-[var(--text-tertiary)]">
            Each line tracks a potential adverse event. Lines above the threshold indicate statistically significant safety signals.
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {availableEvents.slice(0, 10).map((event, idx) => {
            const selected = selectedEvents.includes(event);
            const color = lineColors[idx % lineColors.length];
            return (
              <button
                key={event}
                type="button"
                onClick={() => onToggleEvent(event)}
                className="rounded-lg px-3 py-1.5 text-xs font-medium transition-all duration-200"
                style={{
                  backgroundColor: selected ? `${color}18` : "rgba(255,255,255,0.03)",
                  color: selected ? color : "var(--text-secondary)",
                  boxShadow: selected ? `inset 0 0 0 1px ${color}40, 0 0 12px ${color}10` : "none",
                }}
              >
                <span className="mr-1.5 inline-block h-2 w-2 rounded-full" style={{ backgroundColor: selected ? color : "transparent" }} />
                {event}
              </button>
            );
          })}
        </div>
      </div>
      <div className="mb-3 flex flex-wrap items-center gap-4 text-[11px] text-[var(--text-tertiary)]">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-[#6ba5d4]" />
          Agent prediction issued
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-[#5ec4b6]" />
          New signal detected
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-[#ef4444]" />
          FDA action
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-[1px] w-4 border-t border-dashed border-[rgba(148,163,184,0.5)]" />
          Safety threshold (ROR=1)
        </span>
      </div>

      <div className="h-[460px] w-full lg:h-[520px]">
        <ResponsiveContainer>
          <ComposedChart data={chartRows} margin={{ top: 16, right: 24, bottom: 12, left: 0 }}>
            <defs>
              {selectedEvents.map((event, idx) => {
                const color = lineColors[idx % lineColors.length];
                return (
                  <linearGradient key={`grad-${event}`} id={`area-${event.replace(/\s/g, "_")}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={color} stopOpacity={0.15} />
                    <stop offset="100%" stopColor={color} stopOpacity={0.01} />
                  </linearGradient>
                );
              })}
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255, 255, 255, 0.035)" vertical={false} />
            <XAxis
              dataKey="quarter"
              tick={{ fill: "var(--text-secondary)", fontSize: 11 }}
              tickLine={{ stroke: "rgba(255,255,255,0.06)" }}
              axisLine={{ stroke: "rgba(255,255,255,0.08)" }}
            />
            <YAxis
              tick={{ fill: "var(--text-secondary)", fontSize: 11 }}
              label={{ value: "ROR", angle: -90, position: "insideLeft", fill: "var(--text-tertiary)", fontSize: 11, dx: -4 }}
              tickLine={{ stroke: "rgba(255,255,255,0.06)" }}
              axisLine={{ stroke: "rgba(255,255,255,0.08)" }}
            />
            <Tooltip
              cursor={{ stroke: "var(--accent)", strokeWidth: 1, strokeDasharray: "4 4", opacity: 0.4 }}
              content={({ active, payload, label }) => {
                if (!active || !payload || !label) {
                  return null;
                }

                return (
                  <div className="rounded-xl border border-white/[0.1] bg-[var(--bg-root)]/95 p-4 text-xs shadow-[0_8px_32px_rgba(0,0,0,0.5)] backdrop-blur-md">
                    <p className="mb-2.5 text-[10px] font-semibold uppercase tracking-[0.15em] text-[var(--accent)]">{label}</p>
                    <div className="space-y-2.5">
                      {payload.map((linePayload) => {
                        if (!linePayload.dataKey || typeof linePayload.dataKey !== "string") {
                          return null;
                        }
                        const point = pointsByQuarterEvent.get(`${label}::${linePayload.dataKey}`);
                        if (!point) {
                          return null;
                        }
                        return (
                          <div key={`${label}-${linePayload.dataKey}`} className="flex items-start gap-2">
                            <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: linePayload.color }} />
                            <div>
                              <p className="font-semibold text-[var(--text-primary)]">
                                {linePayload.dataKey}
                              </p>
                              <p className="text-[var(--text-secondary)]">
                                ROR <span className="font-semibold" style={{ color: linePayload.color }}>{formatMaybe(point.ror)}</span> &middot; CI {formatMaybe(point.ror_ci_lower)}&ndash;{formatMaybe(point.ror_ci_upper)}
                              </p>
                              <p className="text-[var(--text-tertiary)]">
                                {point.report_count} rpt &middot; {point.cumulative_count} cum &middot; {point.trajectory}
                              </p>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              }}
            />
            <Legend
              content={() => null}
            />
            <ReferenceLine
              y={1}
              stroke="rgba(148, 163, 184, 0.5)"
              strokeDasharray="4 4"
              label={{
                value: "Safety threshold (ROR = 1.0)",
                fill: "rgba(148, 163, 184, 0.9)",
                fontSize: 10,
                position: "insideBottomRight",
              }}
            />

            {visibleFdaMarkers.map((action) => {
              return (
                <ReferenceLine
                  key={action.id}
                  x={action.quarter}
                  stroke="#ef4444"
                  strokeDasharray="4 4"
                  label={{
                    value: `FDA: ${action.title.slice(0, 30)}`,
                    angle: -90,
                    position: "insideTopRight",
                    fill: "#ef4444",
                    fontSize: 10,
                  }}
                />
              );
            })}

            {visiblePredictionMarkers.map((entry) => (
              <ReferenceLine
                key={`prediction-${entry.prediction.id}`}
                x={entry.prediction.created_at_quarter}
                stroke="#6ba5d4"
                strokeDasharray="2 6"
                label={{
                  value: "Pre",
                  angle: -90,
                  position: "insideTopLeft",
                  fill: "#6ba5d4",
                  fontSize: 11,
                  fontWeight: 600,
                }}
              />
            ))}

            {ileusEmergence && chartRows.some((row) => row.quarter === ileusEmergence.quarter) ? (
              <ReferenceLine
                x={ileusEmergence.quarter}
                stroke="#5ec4b6"
                strokeDasharray="5 3"
                label={{
                  value: "Ileus emerges",
                  angle: -90,
                  position: "insideTopRight",
                  fill: "#5ec4b6",
                  fontSize: 10,
                  fontWeight: 600,
                }}
              />
            ) : null}

            {chartRows.some((row) => row.quarter === activeQuarter) && (
              <ReferenceLine
                x={activeQuarter}
                stroke="var(--accent)"
                strokeWidth={1.5}
                strokeOpacity={0.35}
              />
            )}

            {markerLines.map((marker) => (
              <ReferenceLine
                key={`reinterpret-${marker.quarter}`}
                x={marker.quarter}
                stroke="var(--accent)"
                strokeDasharray="3 3"
                label={{
                  value: marker.count > 1 ? `reinterpret (${marker.count})` : "reinterpret",
                  angle: -90,
                  position: "insideTopLeft",
                  fill: "var(--accent)",
                  fontSize: 10,
                }}
              />
            ))}

            {selectedEvents.map((event, idx) => (
              <Area
                key={`area-${event}`}
                type="monotone"
                dataKey={event}
                fill={`url(#area-${event.replace(/\s/g, "_")})`}
                stroke="none"
                connectNulls
                isAnimationActive
                animationDuration={400}
              />
            ))}

            {selectedEvents.map((event, idx) => (
              <Line
                key={event}
                type="monotone"
                dataKey={event}
                stroke={lineColors[idx % lineColors.length]}
                strokeWidth={2.5}
                dot={{ r: 3, strokeWidth: 0, fill: lineColors[idx % lineColors.length] }}
                activeDot={{ r: 5, strokeWidth: 2, stroke: "var(--bg-root)", fill: lineColors[idx % lineColors.length] }}
                connectNulls
                isAnimationActive
                animationDuration={400}
              />
            ))}

            {quarters.length > 4 ? (
              <Brush
                dataKey="quarter"
                height={18}
                stroke="var(--accent)"
                fill="var(--bg-card)"
                startIndex={Math.max(0, quarters.length - 10)}
                endIndex={Math.max(quarters.length - 1, 0)}
                onChange={(range) => {
                  if (range?.startIndex === undefined || range.endIndex === undefined) {
                    setBrushRange(null);
                    return;
                  }
                  setBrushRange({
                    startIndex: range.startIndex,
                    endIndex: range.endIndex,
                  });
                }}
              />
            ) : null}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
