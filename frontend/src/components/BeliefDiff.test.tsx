import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Belief, BeliefDiff as BeliefDiffType } from "../types/shared";
import { BeliefDiff } from "./BeliefDiff";

const giQ1: Belief = {
  id: "gi-1",
  drug_id: "semaglutide",
  question_hash: "sha256:gi",
  question_text: "Are there emerging GI motility concerns for semaglutide?",
  answer_text: "Early GI state",
  confidence_score: 36,
  evidence_report_ids: [],
  episodic_ids_used: [],
  created_at: "2026-01-01T00:00:00Z",
  quarter_context: "2018-Q1",
};

const giQ3: Belief = {
  ...giQ1,
  id: "gi-2",
  answer_text: "Later GI state",
  confidence_score: 66,
  created_at: "2026-01-02T00:00:00Z",
  quarter_context: "2023-Q3",
};

const safetyQ1: Belief = {
  ...giQ1,
  id: "safety-1",
  question_hash: "sha256:safety",
  question_text: "What is the overall safety profile of semaglutide?",
  quarter_context: "2018-Q1",
};

const safetyQ3: Belief = {
  ...safetyQ1,
  id: "safety-2",
  quarter_context: "2023-Q3",
  created_at: "2026-01-03T00:00:00Z",
};

const diff: BeliefDiffType = {
  before: giQ1,
  after: giQ3,
  text_diff: [
    { type: "removed", text: "old" },
    { type: "added", text: "new" },
  ],
  confidence_delta: 30,
  new_evidence_ids: ["S-1"],
  reinterpreted_report_ids: ["S-9"],
  triggered_by_quarter: "2023-Q3",
};

describe("BeliefDiff", () => {
  it("auto-requests compare when a diff is not already loaded", async () => {
    const onRequestDiff = vi.fn(async () => undefined);
    const onOpenEvidence = vi.fn();

    render(
      <BeliefDiff
        beliefs={[giQ1, giQ3, safetyQ1, safetyQ3]}
        diff={null}
        onRequestDiff={onRequestDiff}
        onOpenEvidence={onOpenEvidence}
        loading={false}
        currentQuarter="2023-Q3"
      />,
    );

    await waitFor(() => {
      expect(onRequestDiff).toHaveBeenCalledWith("gi-1", "gi-2");
    });
  });

  it("reuses the loaded diff and keeps evidence chips clickable", () => {
    const onRequestDiff = vi.fn(async () => undefined);
    const onOpenEvidence = vi.fn();

    render(
      <BeliefDiff
        beliefs={[giQ1, giQ3, safetyQ1, safetyQ3]}
        diff={diff}
        onRequestDiff={onRequestDiff}
        onOpenEvidence={onOpenEvidence}
        loading={false}
        currentQuarter="2023-Q3"
      />,
    );

    expect(screen.getByText("2018-Q1")).toBeInTheDocument();
    expect(screen.getByText("2023-Q3")).toBeInTheDocument();
    expect(screen.getByText(/Delta confidence: \+30/i)).toBeInTheDocument();
    expect(screen.queryByText(/sha256:/i)).not.toBeInTheDocument();
    expect(onRequestDiff).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "S-9" }));
    expect(onOpenEvidence).toHaveBeenCalledWith("S-9");
  });
});
