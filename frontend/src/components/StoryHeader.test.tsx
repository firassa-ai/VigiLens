import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { BeliefDiff, ScorecardEntry } from "../types/shared";
import { StoryHeader } from "./StoryHeader";

const primaryReceipt: ScorecardEntry = {
  prediction: {
    id: "p-1",
    drug_id: "semaglutide",
    adverse_event: "Ileus",
    predicted_action: "label_change",
    confidence: 76,
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
  actual_fda_action: {
    id: "action-1",
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
  result: "validated",
};

const beliefDiff: BeliefDiff = {
  before: {
    id: "belief-before",
    drug_id: "semaglutide",
    question_hash: "q-1",
    question_text: "What changed?",
    answer_text: "This quarter changed the interpretation.",
    confidence_score: 64,
    evidence_report_ids: ["S-1001"],
    episodic_ids_used: ["episodic:semaglutide:2023-Q3"],
    created_at: "2023-09-01T00:00:00Z",
    quarter_context: "2023-Q2",
  },
  after: {
    id: "belief-after",
    drug_id: "semaglutide",
    question_hash: "q-1",
    question_text: "What changed?",
    answer_text: "Earlier GI reports now look like precursor evidence for ileus.",
    confidence_score: 83,
    evidence_report_ids: ["S-1001", "S-2001"],
    episodic_ids_used: ["episodic:semaglutide:2023-Q3"],
    created_at: "2023-10-01T00:00:00Z",
    quarter_context: "2023-Q3",
  },
  text_diff: [],
  confidence_delta: 19,
  new_evidence_ids: ["S-2001"],
  reinterpreted_report_ids: ["S-1001", "S-2001"],
  triggered_by_quarter: "2023-Q3",
};

describe("StoryHeader", () => {
  it("renders the baseline casefile framing", () => {
    render(
      <StoryHeader
        viewingQuarter="2022-Q2"
        totalReportsLoaded={1234}
        demoStage="baseline"
        memoryStatusLabel="Memory-backed"
        memoryStatusTone="ok"
      />,
    );

    expect(screen.getByText(/Baseline Casefile/i)).toBeInTheDocument();
    expect(screen.getByText(/Viewing 2022-Q2/i)).toBeInTheDocument();
    expect(screen.getByText(/1,234 reports/i)).toBeInTheDocument();
    expect(screen.getByText(/Memory-backed/i)).toBeInTheDocument();
    expect(screen.getByText(/Semaglutide starts as familiar GI noise/i)).toBeInTheDocument();
    expect(screen.getByText(/The first act is calm by design/i)).toBeInTheDocument();
  });

  it("switches to reveal and validation copy with the staged receipts", () => {
    const { rerender } = render(
      <StoryHeader
        viewingQuarter="2023-Q3"
        totalReportsLoaded={2227}
        demoStage="reveal"
        memoryStatusLabel="Memory-backed"
        beliefDiff={beliefDiff}
        primaryReceipt={primaryReceipt}
        secondaryReceiptCount={1}
      />,
    );

    expect(screen.getByText(/Reveal Quarter/i)).toBeInTheDocument();
    expect(screen.getByText(/Earlier reports are being reclassified/i)).toBeInTheDocument();
    expect(screen.getByText(/2 reinterpreted reports/i)).toBeInTheDocument();
    expect(screen.getByText(/Lead with the reinterpretation moment/i)).toBeInTheDocument();

    rerender(
      <StoryHeader
        viewingQuarter="2023-Q4"
        totalReportsLoaded={2237}
        demoStage="validation"
        memoryStatusLabel="Memory-backed"
        primaryReceipt={primaryReceipt}
        secondaryReceiptCount={1}
      />,
    );

    expect(screen.getByText(/^FDA Receipt$/i)).toBeInTheDocument();
    expect(screen.getByText(/The ileus forecast now has a concrete FDA receipt/i)).toBeInTheDocument();
    expect(screen.getByText(/Primary receipt: Ileus added to label/i)).toBeInTheDocument();
    expect(screen.getByText(/Lead with the ileus receipt/i)).toBeInTheDocument();
  });
});
