import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Belief, BeliefDiff } from "../types/shared";
import { BeliefRevisionHero } from "./BeliefRevisionHero";

const beforeBelief: Belief = {
  id: "belief-before",
  drug_id: "semaglutide",
  question_hash: "sha256:gi",
  question_text: "Are there emerging GI motility concerns for semaglutide?",
  answer_text: "As of 2023-Q3, GI motility monitoring stays routine.",
  confidence_score: 76,
  evidence_report_ids: ["S-2023Q3A"],
  episodic_ids_used: [],
  created_at: "2026-03-14T00:00:00Z",
  quarter_context: "2023-Q3",
};

const afterBelief: Belief = {
  ...beforeBelief,
  id: "belief-after",
  answer_text: "As of 2023-Q4, GI motility monitoring shows 5 active signals.",
  confidence_score: 76,
  evidence_report_ids: ["S-2023Q3A", "S-2023Q2A"],
  episodic_ids_used: [],
  created_at: "2026-03-14T00:00:01Z",
  quarter_context: "2023-Q4",
};

const diff: BeliefDiff = {
  before: beforeBelief,
  after: afterBelief,
  text_diff: [],
  confidence_delta: 0,
  new_evidence_ids: [],
  reinterpreted_report_ids: ["S-2023Q3A", "S-2023Q2A"],
  triggered_by_quarter: "2023-Q4",
};

describe("BeliefRevisionHero", () => {
  it("opens evidence reports and shows fallback memory receipts", () => {
    const onOpenEvidence = vi.fn();
    const onOpenMemory = vi.fn();

    render(
      <BeliefRevisionHero
        activeQuarter="2023-Q4"
        diff={diff}
        memoryReceiptIds={[
          "episodic:semaglutide:2023-Q4",
          "episodic:semaglutide:2023-Q3",
        ]}
        onOpenEvidence={onOpenEvidence}
        onOpenMemory={onOpenMemory}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "S-2023Q3A" }));
    expect(onOpenEvidence).toHaveBeenCalledWith("S-2023Q3A");

    fireEvent.click(
      screen.getByRole("button", { name: "episodic:semaglutide:2023-Q4" }),
    );
    expect(onOpenMemory).toHaveBeenCalledWith("episodic:semaglutide:2023-Q4");
  });
});
