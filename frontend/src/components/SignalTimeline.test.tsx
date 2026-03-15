import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { FDAAction, ScorecardEntry, SignalPoint } from "../types/shared";
import { filterVisibleTimelineMarkers, quarterIsAtOrBefore, SignalTimeline } from "./SignalTimeline";

const points: SignalPoint[] = [
  {
    quarter: "2023-Q2",
    adverse_event: "Constipation",
    report_count: 10,
    cumulative_count: 40,
    drug_total_cumulative: 120,
    ror: 4.2,
    ror_ci_lower: 3.5,
    ror_ci_upper: 5.1,
    prr: 2.1,
    chi_squared: 10.0,
    signal_detected: true,
    trajectory: "emerging",
  },
  {
    quarter: "2023-Q3",
    adverse_event: "Constipation",
    report_count: 12,
    cumulative_count: 52,
    drug_total_cumulative: 148,
    ror: 5.0,
    ror_ci_lower: 4.0,
    ror_ci_upper: 6.1,
    prr: 2.3,
    chi_squared: 12.0,
    signal_detected: true,
    trajectory: "accelerating",
  },
];

const fdaActions: FDAAction[] = [
  {
    id: "fda-1",
    date: "2023-09-01",
    type: "label_change",
    title: "Ileus added to label",
    description: "",
    source_url: "https://example.com",
    scope: {
      type: "drug",
      key: "semaglutide",
      label: "Semaglutide",
    },
  },
];

const predictionEntries: ScorecardEntry[] = [
  {
    prediction: {
      id: "pred-1",
      drug_id: "semaglutide",
      adverse_event: "Ileus",
      predicted_action: "label_change",
      confidence: 80,
      predicted_date_range: ["2023-01-01", "2024-01-01"],
      created_at_quarter: "2022-Q4",
      basis: {
        type: "cross_signal_guardrail",
        summary: "Constipation stayed strongly elevated by 2022-Q4.",
      },
      scope: {
        type: "drug",
        key: "semaglutide",
        label: "Semaglutide",
      },
      supporting_event: {
        adverse_event: "Constipation",
        quarter: "2022-Q4",
        trajectory: "stable",
        cumulative_count: 20,
        evidence_report_ids: ["S-1001"],
        evidence_api_paths: ["/api/v1/evidence/S-1001"],
      },
    },
    actual_fda_action: null,
    result: "validated",
  },
];

describe("SignalTimeline", () => {
  it("accepts reinterpretation markers without crashing", async () => {
    render(
      <div style={{ width: 1200, height: 520 }}>
        <SignalTimeline
          points={points}
          fdaActions={[]}
          selectedEvents={["Constipation"]}
          onToggleEvent={vi.fn()}
          activeQuarter="2023-Q3"
          reinterpretationMarkers={[{ quarter: "2023-Q3", reportId: "S-2023Q3A" }]}
        />
      </div>,
    );

    expect(screen.getByText("Signal Trajectory Field")).toBeInTheDocument();
    expect(screen.getByText("Constipation")).toBeInTheDocument();
  });

  it("computes marker visibility by active quarter", async () => {
    expect(quarterIsAtOrBefore("2022-Q4", "2023-Q1")).toBe(true);
    expect(quarterIsAtOrBefore("2023-Q3", "2022-Q4")).toBe(false);

    const early = filterVisibleTimelineMarkers({
      fdaActions,
      predictionEntries,
      activeQuarter: "2022-Q4",
    });
    expect(early.visiblePredictionQuarters).toContain("2022-Q4");
    expect(early.visibleFdaQuarters).toHaveLength(0);

    const late = filterVisibleTimelineMarkers({
      fdaActions,
      predictionEntries,
      activeQuarter: "2023-Q3",
    });
    expect(late.visiblePredictionQuarters).toContain("2022-Q4");
    expect(late.visibleFdaQuarters).toContain("2023-Q3");
  });
});
