import { describe, expect, it } from "vitest";

import type { ScorecardEntry } from "../types/shared";
import {
  buildDemoReceiptMetricSuffix,
  countScorecardEntries,
  splitScorecardEntries,
} from "./scorecardPresentation";

const entries: ScorecardEntry[] = [
  {
    prediction: {
      id: "validated-1",
      drug_id: "semaglutide",
      adverse_event: "Ileus",
      predicted_action: "label_change",
      confidence: 78,
      predicted_date_range: ["2022-10-01", "2023-12-31"],
      created_at_quarter: "2022-Q4",
      basis: {
        type: "cross_signal_guardrail",
        summary: "Ileus forecast.",
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
  {
    prediction: {
      id: "pending-1",
      drug_id: "semaglutide",
      adverse_event: "Suicidal ideation",
      predicted_action: "safety_communication",
      confidence: 68,
      predicted_date_range: ["2023-07-01", "2024-06-30"],
      created_at_quarter: "2023-Q2",
      basis: {
        type: "sentinel_report_guardrail",
        summary: "Pending forecast.",
      },
      scope: {
        type: "drug",
        key: "semaglutide",
        label: "Semaglutide",
      },
      supporting_event: {
        adverse_event: "Suicidal ideation",
        quarter: "2023-Q2",
        trajectory: "stable",
        cumulative_count: 3,
        evidence_report_ids: ["S-2001"],
        evidence_api_paths: ["/api/v1/evidence/S-2001"],
      },
    },
    actual_fda_action: null,
    result: "pending",
  },
  {
    prediction: {
      id: "early-1",
      drug_id: "semaglutide",
      adverse_event: "Gastroparesis",
      predicted_action: "warning",
      confidence: 61,
      predicted_date_range: ["2022-01-01", "2022-12-31"],
      created_at_quarter: "2022-Q1",
      basis: {
        type: "signal_threshold",
        summary: "Early forecast.",
      },
      scope: {
        type: "drug",
        key: "semaglutide",
        label: "Semaglutide",
      },
      supporting_event: {
        adverse_event: "Gastroparesis",
        quarter: "2022-Q1",
        trajectory: "emerging",
        cumulative_count: 4,
        evidence_report_ids: ["S-3001"],
        evidence_api_paths: ["/api/v1/evidence/S-3001"],
      },
    },
    actual_fda_action: null,
    result: "early",
  },
  {
    prediction: {
      id: "missed-1",
      drug_id: "semaglutide",
      adverse_event: "Chest pain",
      predicted_action: "warning",
      confidence: 70,
      predicted_date_range: ["2019-01-01", "2020-01-01"],
      created_at_quarter: "2019-Q1",
      basis: {
        type: "sentinel_report_guardrail",
        summary: "Missed forecast.",
      },
      scope: {
        type: "drug",
        key: "semaglutide",
        label: "Semaglutide",
      },
      supporting_event: {
        adverse_event: "Chest pain",
        quarter: "2019-Q1",
        trajectory: "emerging",
        cumulative_count: 11,
        evidence_report_ids: ["S-4001"],
        evidence_api_paths: ["/api/v1/evidence/S-4001"],
      },
    },
    actual_fda_action: null,
    result: "missed",
  },
];

describe("scorecardPresentation", () => {
  it("splits demo entries into active and archived groups", () => {
    const split = splitScorecardEntries(entries, "demo");
    expect(split.activeEntries.map((entry) => entry.prediction.id)).toEqual([
      "validated-1",
      "pending-1",
      "early-1",
    ]);
    expect(split.archivedEntries.map((entry) => entry.prediction.id)).toEqual([
      "missed-1",
    ]);
  });

  it("keeps generic entries untouched", () => {
    const split = splitScorecardEntries(entries, "generic");
    expect(split.activeEntries).toEqual(entries);
    expect(split.archivedEntries).toEqual([]);
  });

  it("counts scorecard results and formats the demo metric suffix", () => {
    const counts = countScorecardEntries(entries);
    expect(counts).toEqual({
      validated: 1,
      pending: 1,
      early: 1,
      missed: 1,
      active: 3,
      total: 4,
    });
    expect(buildDemoReceiptMetricSuffix(counts)).toBe(
      "validated, 1 pending, 1 early",
    );
  });
});
