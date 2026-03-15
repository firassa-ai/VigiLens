import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ScorecardEntry } from "../types/shared";
import { PredictionScorecard } from "./PredictionScorecard";

const entries: ScorecardEntry[] = [
  {
    prediction: {
      id: "pending-1",
      drug_id: "semaglutide",
      adverse_event: "Gastroparesis",
      predicted_action: "label_change",
      confidence: 60,
      predicted_date_range: ["2024-01-01", "2024-12-31"],
      created_at_quarter: "2023-Q2",
      basis: {
        type: "signal_threshold",
        summary:
          "Gastroparesis met the deterministic signal threshold by 2023-Q2.",
      },
      scope: {
        type: "drug",
        key: "semaglutide",
        label: "Semaglutide",
      },
      supporting_event: {
        adverse_event: "Gastroparesis",
        quarter: "2023-Q2",
        trajectory: "emerging",
        cumulative_count: 4,
        evidence_report_ids: ["S-2001"],
        evidence_api_paths: ["/api/v1/evidence/S-2001"],
      },
      verification: {
        status: "supported",
        summary:
          "DailyMed language and literature both align with this emerging GI motility concern.",
        checked_at: "2026-03-12T08:00:00Z",
        queries: ["semaglutide gastroparesis label warning"],
        citations: [
          {
            title: "DailyMed semaglutide label",
            url: "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=test",
            source_type: "dailymed",
          },
        ],
        source_types: ["dailymed"],
      },
    },
    actual_fda_action: null,
    result: "pending",
  },
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
        summary:
          "Constipation stayed strongly elevated by 2022-Q4, so the deterministic guardrail emitted an Ileus label-change forecast.",
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
  },
  {
    prediction: {
      id: "missed-1",
      drug_id: "semaglutide",
      adverse_event: "Chest pain",
      predicted_action: "warning",
      confidence: 71,
      predicted_date_range: ["2019-01-01", "2020-01-01"],
      created_at_quarter: "2019-Q1",
      basis: {
        type: "sentinel_report_guardrail",
        summary: "Chest pain met the priority-review threshold by 2019-Q1.",
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
        evidence_report_ids: ["S-1999"],
        evidence_api_paths: ["/api/v1/evidence/S-1999"],
      },
    },
    actual_fda_action: null,
    result: "missed",
  },
];

const entriesWithTwoValidated: ScorecardEntry[] = [
  ...entries,
  {
    prediction: {
      id: "validated-2",
      drug_id: "semaglutide",
      adverse_event: "Suicidal ideation",
      predicted_action: "safety_communication",
      confidence: 68,
      predicted_date_range: ["2023-07-01", "2024-06-30"],
      created_at_quarter: "2023-Q2",
      basis: {
        type: "sentinel_report_guardrail",
        summary:
          "Suicidal ideation crossed the serious-event guardrail by 2023-Q2.",
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
        evidence_report_ids: ["S-3001"],
        evidence_api_paths: ["/api/v1/evidence/S-3001"],
      },
    },
    actual_fda_action: {
      id: "action-2",
      date: "2024-01-11",
      type: "safety_communication",
      title: "FDA update on GLP-1 reports of suicidal thoughts/actions",
      description: "",
      source_url: "https://example.com/fda-glp1-update",
      scope: {
        type: "class",
        key: "glp1_receptor_agonists",
        label: "GLP-1 receptor agonists",
      },
    },
    result: "validated",
  },
];

describe("PredictionScorecard", () => {
  it("shows reveal-stage framing with a primary receipt and tracked secondary outcome", () => {
    render(
      <PredictionScorecard
        entries={entries}
        loading={false}
        asOfQuarter="2023-Q3"
        demoStage="reveal"
      />,
    );

    expect(screen.getAllByText(/VALIDATED/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/Ileus -> label change/i)).toBeInTheDocument();
    expect(screen.getByText(/Lead time: about 11 months/i)).toBeInTheDocument();
    expect(screen.getByText(/As of 2023-Q3/i)).toBeInTheDocument();
    expect(
      screen.getByText(/1 validated receipt and 1 open follow-up/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/Lead receipt/i)).toBeInTheDocument();
    expect(
      screen.getByText(/1 validated \+ 1 pending receipts/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/Also tracked/i)).toBeInTheDocument();
    expect(
      screen.queryByText(/Chest pain -> warning/i),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/cross signal guardrail/i)).toBeInTheDocument();
    expect(screen.getByText(/FDA scope Semaglutide/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Stage-specific framing controls the emphasis/i),
    ).toBeInTheDocument();
  });

  it("prioritizes the ileus FDA receipt in validation stage", () => {
    render(
      <PredictionScorecard
        entries={entries}
        loading={false}
        asOfQuarter="2023-Q4"
        demoStage="validation"
      />,
    );

    expect(screen.getByText(/^Primary receipt$/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Primary receipt: Ileus added to label/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/^Additional tracked outcomes$/i),
    ).toBeInTheDocument();
  });

  it("shows the second validated receipt alongside the lead receipt when two are linked", () => {
    render(
      <PredictionScorecard
        entries={entriesWithTwoValidated}
        loading={false}
        demoStage="validation"
      />,
    );

    expect(screen.getByText(/^Primary receipt$/i)).toBeInTheDocument();
    expect(screen.getByText(/Ileus -> label change/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Suicidal ideation -> safety communication/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/Gastroparesis -> label change/i),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(/2 validated \+ 1 pending receipts/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /click for more \(1\)/i })).toBeInTheDocument();
    expect(screen.getAllByText(/^VALIDATED$/i, { selector: "span" }).length).toBeGreaterThanOrEqual(2);
  });

  it("reveals the hidden tracked outcomes after clicking for more", () => {
    render(
      <PredictionScorecard
        entries={entriesWithTwoValidated}
        loading={false}
        demoStage="validation"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /click for more \(1\)/i }));

    expect(screen.getByText(/Gastroparesis -> label change/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /show less/i })).toBeInTheDocument();
  });

  it("keeps not-pursued entries out of the demo list but exposes them in analyst stage", () => {
    render(
      <PredictionScorecard
        entries={entries}
        loading={false}
        asOfQuarter="2023-Q4"
        demoStage="analyst"
      />,
    );

    expect(
      screen.getByText(/^Not pursued$/i, { selector: "p" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/archived receipt horizon/i)).toBeInTheDocument();
    expect(screen.getByText(/Chest pain -> warning/i)).toBeInTheDocument();
    expect(
      screen.getByText(/^NOT PURSUED$/i, { selector: "span" }),
    ).toBeInTheDocument();
  });

  it("opens foresight memory from provenance chip", () => {
    const onOpenForesightMemory = vi.fn();
    render(
      <PredictionScorecard
        entries={entries}
        loading={false}
        asOfQuarter="2023-Q3"
        showMemorySources
        onOpenForesightMemory={onOpenForesightMemory}
        demoStage="validation"
      />,
    );

    const memoryButton = screen.getByRole("button", {
      name: /vigl_semaglutide_2022Q4_foresight/i,
    });
    fireEvent.click(memoryButton);
    expect(onOpenForesightMemory).toHaveBeenCalledWith(
      expect.objectContaining({
        prediction: expect.objectContaining({ id: "validated-1" }),
      }),
      "vigl_semaglutide_2022Q4_foresight",
    );
  });

  it("switches to generic summary copy outside the semaglutide demo shell", () => {
    render(
      <PredictionScorecard
        entries={entries}
        loading={false}
        asOfQuarter="2023-Q4"
        presentationMode="generic"
        receiptSummary="1 validated regulatory receipt is already linked."
        watchlistSummary="2 watchlist alerts and 1 label-gap cue are active in the casefile header."
      />,
    );

    expect(
      screen.getByText(/1 validated regulatory receipt is already linked/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/2 watchlist alerts and 1 label-gap cue/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/Chest pain -> warning/i)).toBeInTheDocument();
    expect(
      screen.queryByText(/Forecasts become receipts as the case advances/i),
    ).not.toBeInTheDocument();
  });

  it("renders proof metadata when verification is attached to a forecast", () => {
    render(
      <PredictionScorecard
        entries={entries}
        loading={false}
        asOfQuarter="2023-Q4"
        presentationMode="generic"
      />,
    );

    expect(screen.getByText(/Proof supported/i)).toBeInTheDocument();
    expect(
      screen.getByText(/DailyMed language and literature/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /DailyMed semaglutide label/i }),
    ).toBeInTheDocument();
  });
});
