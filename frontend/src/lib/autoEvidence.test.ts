import { describe, expect, it } from "vitest";

import type { Belief, SignalPoint } from "../types/shared";
import {
  buildAutoEvidenceQuestion,
  pickBeliefPairForQuarterDiff,
  pickBeliefPairForQuarters,
  resolveSpotlightSignal,
} from "./autoEvidence";

function point(overrides: Partial<SignalPoint> & Pick<SignalPoint, "adverse_event" | "quarter">): SignalPoint {
  return {
    quarter: overrides.quarter,
    adverse_event: overrides.adverse_event,
    report_count: overrides.report_count ?? 1,
    cumulative_count: overrides.cumulative_count ?? overrides.report_count ?? 1,
    drug_total_cumulative: overrides.drug_total_cumulative ?? 24,
    ror: overrides.ror ?? 1.2,
    ror_ci_lower: overrides.ror_ci_lower ?? 1.01,
    ror_ci_upper: overrides.ror_ci_upper ?? 2.0,
    prr: overrides.prr ?? 1.1,
    chi_squared: overrides.chi_squared ?? 2.0,
    signal_detected: overrides.signal_detected ?? false,
    trajectory: overrides.trajectory ?? "stable",
  };
}

function belief(overrides: Partial<Belief> & Pick<Belief, "id" | "question_hash" | "question_text" | "created_at" | "quarter_context">): Belief {
  return {
    id: overrides.id,
    drug_id: overrides.drug_id ?? "semaglutide",
    question_hash: overrides.question_hash,
    question_text: overrides.question_text,
    answer_text: overrides.answer_text ?? "answer",
    confidence_score: overrides.confidence_score ?? 80,
    evidence_report_ids: overrides.evidence_report_ids ?? [],
    episodic_ids_used: overrides.episodic_ids_used ?? [],
    created_at: overrides.created_at,
    quarter_context: overrides.quarter_context,
  };
}

describe("resolveSpotlightSignal", () => {
  it("prioritizes newly detected signals over stronger stable signals", () => {
    const previous = [
      point({ quarter: "2022-Q1", adverse_event: "Constipation", signal_detected: true, ror_ci_lower: 3.1, report_count: 30 }),
    ];
    const current = [
      point({ quarter: "2022-Q2", adverse_event: "Constipation", signal_detected: true, trajectory: "stable", ror_ci_lower: 3.2, report_count: 45 }),
      point({ quarter: "2022-Q2", adverse_event: "Ileus", signal_detected: true, trajectory: "emerging", ror_ci_lower: 1.05, report_count: 4 }),
    ];

    expect(resolveSpotlightSignal({ currentQuarterPoints: current, previousQuarterPoints: previous })).toBe("Ileus");
  });

  it("falls back to emerging/accelerating detected signals when no newly detected signal exists", () => {
    const previous = [
      point({ quarter: "2022-Q1", adverse_event: "Constipation", signal_detected: true, trajectory: "stable" }),
      point({ quarter: "2022-Q1", adverse_event: "Nausea", signal_detected: true, trajectory: "stable" }),
    ];
    const current = [
      point({ quarter: "2022-Q2", adverse_event: "Constipation", signal_detected: true, trajectory: "stable", ror_ci_lower: 4.0, report_count: 80 }),
      point({ quarter: "2022-Q2", adverse_event: "Nausea", signal_detected: true, trajectory: "emerging", ror_ci_lower: 1.2, report_count: 5 }),
    ];

    expect(resolveSpotlightSignal({ currentQuarterPoints: current, previousQuarterPoints: previous })).toBe("Nausea");
  });

  it("falls back to strongest overall signal when no signal is detected", () => {
    const current = [
      point({ quarter: "2022-Q2", adverse_event: "Nausea", signal_detected: false, ror_ci_lower: 1.1, report_count: 18 }),
      point({ quarter: "2022-Q2", adverse_event: "Ileus", signal_detected: false, ror_ci_lower: 1.6, report_count: 3 }),
    ];

    expect(resolveSpotlightSignal({ currentQuarterPoints: current, previousQuarterPoints: [] })).toBe("Ileus");
  });
});

describe("buildAutoEvidenceQuestion", () => {
  it("builds deterministic event-focused prompt", () => {
    const question = buildAutoEvidenceQuestion({ drugId: "semaglutide", event: "Ileus" });
    expect(question).toContain("Ileus");
    expect(question).toContain("semaglutide");
  });
});

describe("pickBeliefPairForQuarterDiff", () => {
  it("prefers GI motility question hash when available", () => {
    const beliefs: Belief[] = [
      belief({
        id: "before-overall",
        question_hash: "hash-overall",
        question_text: "What is the overall safety profile of semaglutide?",
        created_at: "2026-02-21T12:00:00Z",
        quarter_context: "2022-Q1",
      }),
      belief({
        id: "after-overall",
        question_hash: "hash-overall",
        question_text: "What is the overall safety profile of semaglutide?",
        created_at: "2026-02-21T12:01:00Z",
        quarter_context: "2022-Q2",
      }),
      belief({
        id: "before-gi",
        question_hash: "hash-gi",
        question_text: "Are there emerging GI motility concerns for semaglutide?",
        created_at: "2026-02-21T12:00:30Z",
        quarter_context: "2022-Q1",
      }),
      belief({
        id: "after-gi-old",
        question_hash: "hash-gi",
        question_text: "Are there emerging GI motility concerns for semaglutide?",
        created_at: "2026-02-21T12:01:10Z",
        quarter_context: "2022-Q2",
      }),
      belief({
        id: "after-gi-new",
        question_hash: "hash-gi",
        question_text: "Are there emerging GI motility concerns for semaglutide?",
        created_at: "2026-02-21T12:01:40Z",
        quarter_context: "2022-Q2",
      }),
    ];

    expect(
      pickBeliefPairForQuarterDiff({
        beliefs,
        activeQuarter: "2022-Q2",
        loadedQuarters: ["2022-Q1", "2022-Q2"],
      }),
    ).toEqual({ beforeId: "before-gi", afterId: "after-gi-new" });
  });

  it("returns null when there is no previous quarter", () => {
    const beliefs: Belief[] = [
      belief({
        id: "only",
        question_hash: "hash",
        question_text: "What is the overall safety profile?",
        created_at: "2026-02-21T12:00:00Z",
        quarter_context: "2022-Q1",
      }),
    ];

    expect(
      pickBeliefPairForQuarterDiff({
        beliefs,
        activeQuarter: "2022-Q1",
        loadedQuarters: ["2022-Q1"],
      }),
    ).toBeNull();
  });
});

describe("pickBeliefPairForQuarters", () => {
  it("selects GI belief pair across non-adjacent quarters when available", () => {
    const beliefs: Belief[] = [
      belief({
        id: "before-safety",
        question_hash: "hash-safety",
        question_text: "What is the overall safety profile of semaglutide?",
        created_at: "2026-02-21T12:00:00Z",
        quarter_context: "2018-Q4",
      }),
      belief({
        id: "after-safety",
        question_hash: "hash-safety",
        question_text: "What is the overall safety profile of semaglutide?",
        created_at: "2026-02-21T12:01:00Z",
        quarter_context: "2023-Q4",
      }),
      belief({
        id: "before-gi",
        question_hash: "hash-gi",
        question_text: "Are there emerging GI motility concerns for semaglutide?",
        created_at: "2026-02-21T12:00:30Z",
        quarter_context: "2018-Q4",
      }),
      belief({
        id: "after-gi",
        question_hash: "hash-gi",
        question_text: "Are there emerging GI motility concerns for semaglutide?",
        created_at: "2026-02-21T12:01:30Z",
        quarter_context: "2023-Q4",
      }),
    ];

    expect(
      pickBeliefPairForQuarters({
        beliefs,
        beforeQuarter: "2018-Q4",
        afterQuarter: "2023-Q4",
      }),
    ).toEqual({ beforeId: "before-gi", afterId: "after-gi" });
  });
});
