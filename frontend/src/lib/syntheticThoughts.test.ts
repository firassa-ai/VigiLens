import { describe, expect, it } from "vitest";

import {
  buildQueryBeliefThought,
  buildQueryEpisodicRecallThought,
  buildQueryForesightRecallThought,
  buildQueryGroundingThought,
  buildQuerySearchThought,
  buildQuarterSummaryThought,
  buildTimeTravelObservationThought,
  claimQuarterOnce,
} from "./syntheticThoughts";

describe("syntheticThoughts", () => {
  it("dedupes quarter claims with a mutable ref object", () => {
    const ref = { current: null as string | null };

    expect(claimQuarterOnce(ref, "2023-Q3")).toBe(true);
    expect(claimQuarterOnce(ref, "2023-Q3")).toBe(false);
    expect(claimQuarterOnce(ref, "2023-Q4")).toBe(true);
  });

  it("builds quarter summary thought from ranked signal data", () => {
    const content = buildQuarterSummaryThought("2023-Q3", [
      {
        quarter: "2023-Q3",
        adverse_event: "Constipation",
        report_count: 52,
        cumulative_count: 612,
        drug_total_cumulative: 2200,
        ror: 3.52,
        ror_ci_lower: 2.91,
        ror_ci_upper: 4.26,
        prr: 2.1,
        chi_squared: 22.4,
        signal_detected: true,
        trajectory: "accelerating",
      },
      {
        quarter: "2023-Q3",
        adverse_event: "Nausea",
        report_count: 68,
        cumulative_count: 1432,
        drug_total_cumulative: 2200,
        ror: 1.88,
        ror_ci_lower: 1.5,
        ror_ci_upper: 2.3,
        prr: 1.4,
        chi_squared: 10.2,
        signal_detected: true,
        trajectory: "stable",
      },
    ]);

    expect(content).toContain("2023-Q3 analysis complete.");
    expect(content).toContain("Constipation leads current pressure");
    expect(content).toContain("2 active signals under surveillance.");
  });

  it("builds time-travel observation thought with forecast context", () => {
    const content = buildTimeTravelObservationThought(
      "2023-Q4",
      [
        {
          quarter: "2023-Q4",
          adverse_event: "Ileus",
          report_count: 13,
          cumulative_count: 78,
          drug_total_cumulative: 2450,
          ror: 4.12,
          ror_ci_lower: 2.74,
          ror_ci_upper: 5.31,
          prr: 2.8,
          chi_squared: 18.3,
          signal_detected: true,
          trajectory: "emerging",
        },
      ],
      [
        {
          prediction: {
            id: "pred-1",
            drug_id: "semaglutide",
            adverse_event: "Ileus",
            predicted_action: "label_change",
            confidence: 86,
            predicted_date_range: ["2023-09-01", "2023-12-31"],
            created_at_quarter: "2023-Q3",
            basis: {
              type: "cross_signal_guardrail",
              summary: "Constipation stayed strongly elevated by 2023-Q3.",
            },
            scope: {
              type: "drug",
              key: "semaglutide",
              label: "Semaglutide",
            },
            supporting_event: {
              adverse_event: "Constipation",
              quarter: "2023-Q3",
              trajectory: "stable",
              cumulative_count: 33,
              evidence_report_ids: ["S-1234"],
              evidence_api_paths: ["/api/v1/evidence/S-1234"],
            },
          },
          result: "pending",
          actual_fda_action: null,
        },
      ],
    );

    expect(content).toContain("Reviewing 2023-Q4:");
    expect(content).toContain("Ileus is the leading signal");
    expect(content).toContain("1 forecast pending validation.");
    expect(content).not.toContain("no signal rows");
  });

  it("builds query-thought helpers with quarter and episodic count context", () => {
    const search = buildQuerySearchThought("Are there emerging GI motility concerns?");
    const grounding = buildQueryGroundingThought(3);
    const episodicRecall = buildQueryEpisodicRecallThought(2);
    const foresightRecall = buildQueryForesightRecallThought(1);
    const belief = buildQueryBeliefThought(
      "2023-Q4",
      "As of 2023-Q4, GI pressure remains elevated.\n\nFAERS limitation...",
    );

    expect(search).toContain("Searching EverMemOS");
    expect(grounding).toContain("Retrieved 3 episodic memories");
    expect(episodicRecall).toContain("EPISODIC recall");
    expect(foresightRecall).toContain("FORESIGHT recall");
    expect(belief).toContain("Belief updated for 2023-Q4");
  });
});
