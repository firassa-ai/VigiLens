import { describe, expect, it } from "vitest";

import type { ScorecardEntry } from "../types/shared";
import { projectScorecardAsOf } from "./scorecardTimeline";

function makePrediction(overrides: Partial<ScorecardEntry["prediction"]>): ScorecardEntry["prediction"] {
  return {
    id: "prediction",
    drug_id: "semaglutide",
    adverse_event: "Ileus",
    predicted_action: "label_change",
    confidence: 78,
    predicted_date_range: ["2022-10-01", "2023-12-31"],
    created_at_quarter: "2022-Q2",
    basis: {
      type: "signal_threshold",
      summary: "Deterministic signal threshold reached.",
    },
    scope: {
      type: "drug",
      key: "semaglutide",
      label: "Semaglutide",
    },
    supporting_event: {
      adverse_event: "Ileus",
      quarter: "2022-Q2",
      trajectory: "emerging",
      cumulative_count: 3,
      evidence_report_ids: ["S-1001"],
      evidence_api_paths: ["/api/v1/evidence/S-1001"],
    },
    ...overrides,
  };
}

function makeAction(overrides: Partial<NonNullable<ScorecardEntry["actual_fda_action"]>>) {
  return {
    id: "action",
    date: "2023-09-01",
    type: "label_change" as const,
    title: "Ileus added to label",
    description: "",
    source_url: "https://example.com/ileus",
    scope: {
      type: "drug" as const,
      key: "semaglutide",
      label: "Semaglutide",
    },
    ...overrides,
  };
}

const entries: ScorecardEntry[] = [
  {
    prediction: makePrediction({
      id: "ileus-prediction",
      adverse_event: "Ileus",
      created_at_quarter: "2022-Q2",
      supporting_event: {
        adverse_event: "Ileus",
        quarter: "2022-Q2",
        trajectory: "emerging",
        cumulative_count: 3,
        evidence_report_ids: ["S-1001"],
        evidence_api_paths: ["/api/v1/evidence/S-1001"],
      },
    }),
    actual_fda_action: makeAction({
      id: "action-ileus",
    }),
    result: "validated",
  },
  {
    prediction: makePrediction({
      id: "suicidal-prediction",
      adverse_event: "Suicidal ideation",
      predicted_action: "safety_communication",
      confidence: 66,
      predicted_date_range: ["2023-04-01", "2024-03-31"],
      created_at_quarter: "2023-Q2",
      basis: {
        type: "sentinel_report_guardrail",
        summary: "Sentinel report guardrail triggered.",
      },
      supporting_event: {
        adverse_event: "Suicidal ideation",
        quarter: "2023-Q2",
        trajectory: "emerging",
        cumulative_count: 1,
        evidence_report_ids: ["S-3001"],
        evidence_api_paths: ["/api/v1/evidence/S-3001"],
      },
    }),
    actual_fda_action: makeAction({
      id: "action-suicidal",
      date: "2024-01-11",
      type: "safety_communication",
      title: "FDA review on suicidal ideation",
      source_url: "https://example.com/suicidal",
      scope: {
        type: "class",
        key: "glp1_receptor_agonists",
        label: "GLP-1 receptor agonists",
      },
    }),
    result: "validated",
  },
  {
    prediction: makePrediction({
      id: "pancreatitis-prediction",
      adverse_event: "Gastroparesis",
      predicted_action: "label_change",
      confidence: 60,
      predicted_date_range: ["2019-07-01", "2020-06-30"],
      created_at_quarter: "2022-Q4",
      supporting_event: {
        adverse_event: "Gastroparesis",
        quarter: "2022-Q4",
        trajectory: "stable",
        cumulative_count: 5,
        evidence_report_ids: ["S-4001"],
        evidence_api_paths: ["/api/v1/evidence/S-4001"],
      },
    }),
    actual_fda_action: null,
    result: "pending",
  },
];

describe("projectScorecardAsOf", () => {
  it("returns unmodified entries when asOfQuarter is null", () => {
    const projected = projectScorecardAsOf(entries, null, "2024-Q1");
    expect(projected).toEqual(entries);
  });

  it("shows predictions as pending before their FDA action quarter", () => {
    const projected = projectScorecardAsOf(entries, "2022-Q3", "2023-Q3");
    expect(projected).toHaveLength(1);
    expect(projected[0].prediction.id).toBe("ileus-prediction");
    expect(projected[0].result).toBe("pending");
    expect(projected[0].actual_fda_action).toBeNull();
  });

  it("keeps validation chronological in time-travel view", () => {
    const projected = projectScorecardAsOf(entries, "2023-Q3", "2023-Q3");
    expect(projected.map((entry) => [entry.prediction.id, entry.result])).toEqual([
      ["ileus-prediction", "validated"],
      ["suicidal-prediction", "pending"],
      ["pancreatitis-prediction", "missed"],
    ]);
    expect(projected[0].actual_fda_action?.id).toBe("action-ileus");
    expect(projected[1].actual_fda_action).toBeNull();
  });

  it("shows validated once viewed quarter reaches action quarter", () => {
    const projected = projectScorecardAsOf(entries, "2024-Q1", "2024-Q1");
    expect(projected.map((entry) => [entry.prediction.id, entry.result])).toEqual([
      ["ileus-prediction", "validated"],
      ["suicidal-prediction", "validated"],
      ["pancreatitis-prediction", "missed"],
    ]);
    expect(projected[1].actual_fda_action?.id).toBe("action-suicidal");
  });
});
