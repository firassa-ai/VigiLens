import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Belief } from "../types/shared";
import { KnowledgeTimeExplorer } from "./KnowledgeTimeExplorer";

const currentBeliefs: Belief[] = [
  {
    id: "b-safety",
    drug_id: "semaglutide",
    question_hash: "sha256:safety",
    question_text: "What is the overall safety profile of semaglutide?",
    answer_text: "Safety answer",
    confidence_score: 52,
    evidence_report_ids: [],
    episodic_ids_used: [],
    created_at: "2026-01-01T00:00:00Z",
    quarter_context: "2023-Q3",
  },
  {
    id: "b-gi",
    drug_id: "semaglutide",
    question_hash: "sha256:gi",
    question_text: "Are there emerging GI motility concerns for semaglutide?",
    answer_text: "GI answer",
    confidence_score: 64,
    evidence_report_ids: [],
    episodic_ids_used: [],
    created_at: "2026-01-01T00:00:00Z",
    quarter_context: "2023-Q3",
  },
  {
    id: "b-reg",
    drug_id: "semaglutide",
    question_hash: "sha256:reg",
    question_text: "What signals warrant regulatory attention for semaglutide?",
    answer_text: "Regulatory answer",
    confidence_score: 71,
    evidence_report_ids: [],
    episodic_ids_used: [],
    created_at: "2026-01-01T00:00:00Z",
    quarter_context: "2023-Q3",
  },
  {
    id: "b-gi-evidence",
    drug_id: "semaglutide",
    question_hash: "sha256:gi-evidence",
    question_text:
      "What report-level evidence supports the GI Motility Harm safety signal for semaglutide? Prioritize serious and hospitalization cases.",
    answer_text: "GI evidence answer",
    confidence_score: 92,
    evidence_report_ids: [],
    episodic_ids_used: [],
    created_at: "2026-01-01T00:00:30Z",
    quarter_context: "2023-Q3",
  },
];

const previousBeliefs: Belief[] = [
  { ...currentBeliefs[0], id: "p-safety", confidence_score: 50, answer_text: "Prev safety", created_at: "2025-12-01T00:00:00Z" },
  { ...currentBeliefs[1], id: "p-gi", confidence_score: 58, answer_text: "Prev gi", created_at: "2025-12-01T00:00:00Z" },
  { ...currentBeliefs[2], id: "p-reg", confidence_score: 55, answer_text: "Prev reg", created_at: "2025-12-01T00:00:00Z" },
  { ...currentBeliefs[3], id: "p-gi-evidence", confidence_score: 88, answer_text: "Prev gi evidence", created_at: "2025-12-01T00:00:00Z" },
];

describe("KnowledgeTimeExplorer belief card", () => {
  it("renders tabbed single-card beliefs and highlights reinterpretation state", async () => {
    render(
      <KnowledgeTimeExplorer
        quarters={["2023-Q2", "2023-Q3"]}
        selectedQuarter="2023-Q3"
        isPlaying={false}
        speedMs={800}
        onChangeQuarter={vi.fn()}
        onTogglePlay={vi.fn()}
        onStep={vi.fn()}
        onJumpStart={vi.fn()}
        onJumpEnd={vi.fn()}
        onSpeedMsChange={vi.fn()}
        signalSnapshot={[]}
        beliefsCurrentQuarter={currentBeliefs}
        beliefsPreviousQuarter={previousBeliefs}
        reinterpretationCount={12}
      />,
    );

    expect(screen.getByRole("button", { name: /Safety Profile/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /GI Motility/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Regulatory/i })).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText(/GI answer/i)).toBeInTheDocument();
    });
    expect(screen.queryByText(/sha256:/i)).not.toBeInTheDocument();
    expect(screen.getByText(/12 earlier reports reinterpreted/i)).toBeInTheDocument();
  });

  it("opens episodic memory from provenance chip", async () => {
    const onOpenEpisodicMemory = vi.fn();
    const beliefsWithMemory: Belief[] = [
      {
        ...currentBeliefs[0],
        episodic_ids_used: ["mem-episodic-1"],
      },
    ];

    render(
      <KnowledgeTimeExplorer
        quarters={["2023-Q2", "2023-Q3"]}
        selectedQuarter="2023-Q3"
        isPlaying={false}
        speedMs={800}
        onChangeQuarter={vi.fn()}
        onTogglePlay={vi.fn()}
        onStep={vi.fn()}
        onJumpStart={vi.fn()}
        onJumpEnd={vi.fn()}
        onSpeedMsChange={vi.fn()}
        signalSnapshot={[]}
        beliefsCurrentQuarter={beliefsWithMemory}
        beliefsPreviousQuarter={[]}
        showMemorySources
        onOpenEpisodicMemory={onOpenEpisodicMemory}
      />,
    );

    const chip = await screen.findByRole("button", { name: /mem-episodic-1/i });
    fireEvent.click(chip);
    expect(onOpenEpisodicMemory).toHaveBeenCalledWith("mem-episodic-1", expect.objectContaining({
      id: "b-safety",
    }));
  });

  it("prefers the canonical GI belief over report-level evidence questions in the GI tab", async () => {
    render(
      <KnowledgeTimeExplorer
        quarters={["2023-Q2", "2023-Q3"]}
        selectedQuarter="2023-Q3"
        isPlaying={false}
        speedMs={800}
        onChangeQuarter={vi.fn()}
        onTogglePlay={vi.fn()}
        onStep={vi.fn()}
        onJumpStart={vi.fn()}
        onJumpEnd={vi.fn()}
        onSpeedMsChange={vi.fn()}
        signalSnapshot={[]}
        beliefsCurrentQuarter={currentBeliefs}
        beliefsPreviousQuarter={previousBeliefs}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /GI Motility/i }));

    await waitFor(() => {
      expect(screen.getByText(/GI answer/i)).toBeInTheDocument();
    });
    expect(
      screen.queryByText(/GI evidence answer/i),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/conf 64/i)).toBeInTheDocument();
  });

  it("keeps the selected belief tab while scrubbing to a different quarter", async () => {
    const { rerender } = render(
      <KnowledgeTimeExplorer
        quarters={["2018-Q1", "2023-Q3"]}
        selectedQuarter="2023-Q3"
        isPlaying={false}
        speedMs={800}
        onChangeQuarter={vi.fn()}
        onTogglePlay={vi.fn()}
        onStep={vi.fn()}
        onJumpStart={vi.fn()}
        onJumpEnd={vi.fn()}
        onSpeedMsChange={vi.fn()}
        signalSnapshot={[]}
        beliefsCurrentQuarter={currentBeliefs}
        beliefsPreviousQuarter={previousBeliefs}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Regulatory/i }));

    await waitFor(() => {
      expect(screen.getByText(/Regulatory answer/i)).toBeInTheDocument();
    });

    const earlierBeliefs = currentBeliefs
      .slice(0, 3)
      .map((belief, index) => ({
        ...belief,
        id: `early-${belief.id}`,
        answer_text:
          index === 2 ? "Earlier regulatory answer" : `Earlier ${belief.id} answer`,
        confidence_score:
          index === 0 ? 68 : index === 1 ? 68 : 70,
        quarter_context: "2018-Q1",
        created_at: "2025-01-01T00:00:00Z",
      }));

    rerender(
      <KnowledgeTimeExplorer
        quarters={["2018-Q1", "2023-Q3"]}
        selectedQuarter="2018-Q1"
        isPlaying={false}
        speedMs={800}
        onChangeQuarter={vi.fn()}
        onTogglePlay={vi.fn()}
        onStep={vi.fn()}
        onJumpStart={vi.fn()}
        onJumpEnd={vi.fn()}
        onSpeedMsChange={vi.fn()}
        signalSnapshot={[]}
        beliefsCurrentQuarter={earlierBeliefs}
        beliefsPreviousQuarter={[]}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText(/Earlier regulatory answer/i)).toBeInTheDocument();
    });
    expect(screen.queryByText(/^Earlier b-gi answer$/i)).not.toBeInTheDocument();
  });
});
