import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { FAERSReport, ScorecardEntry, SignalPoint } from "../types/shared";
import { EvidenceSpotlight } from "./EvidenceSpotlight";

const signalSnapshot: SignalPoint[] = [
  {
    quarter: "2023-Q3",
    adverse_event: "Ileus",
    report_count: 9,
    cumulative_count: 33,
    drug_total_cumulative: 612,
    ror: 1.93,
    ror_ci_lower: 1.0,
    ror_ci_upper: 3.71,
    prr: 1.3,
    chi_squared: 4.5,
    signal_detected: true,
    trajectory: "emerging",
  },
  {
    quarter: "2023-Q3",
    adverse_event: "Constipation",
    report_count: 50,
    cumulative_count: 222,
    drug_total_cumulative: 612,
    ror: 3.56,
    ror_ci_lower: 2.97,
    ror_ci_upper: 4.26,
    prr: 2.1,
    chi_squared: 11.0,
    signal_detected: true,
    trajectory: "stable",
  },
];

const reports: FAERSReport[] = [
  {
    safetyreportid: "S-2",
    version: 1,
    receivedate: "2023-06-05",
    patient_sex: "male",
    patient_age: 55,
    reactions: ["Ileus", "Constipation"],
    suspect_drugs: [],
    concomitant_drugs: [],
    serious: true,
    outcomes: ["Hospitalization"],
    evidence_api_path: "/api/v1/evidence/S-2",
  },
  {
    safetyreportid: "S-1",
    version: 1,
    receivedate: "2023-06-01",
    patient_sex: "female",
    patient_age: 44,
    reactions: ["Nausea"],
    suspect_drugs: [],
    concomitant_drugs: [],
    serious: false,
    outcomes: [],
    evidence_api_path: "/api/v1/evidence/S-1",
  },
];

const scorecard: ScorecardEntry[] = [
  {
    prediction: {
      id: "pred-1",
      drug_id: "semaglutide",
      adverse_event: "Ileus",
      predicted_action: "label_change",
      confidence: 80,
      predicted_date_range: ["2022-12-01", "2023-12-01"],
      created_at_quarter: "2022-Q4",
      basis: {
        type: "cross_signal_guardrail",
        summary: "Constipation stayed strongly elevated by 2022-Q4, so the deterministic guardrail emitted an Ileus label-change forecast.",
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
      title: "Ileus label revision",
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
];

describe("EvidenceSpotlight", () => {
  it("prioritizes reinterpreted reports over serious hospitalization ranking", () => {
    render(
      <EvidenceSpotlight
        activeQuarter="2023-Q3"
        evidence={reports}
        signalSnapshot={signalSnapshot}
        scorecard={[]}
        topSignal={signalSnapshot[1]}
        reinterpretedReportIds={["S-1"]}
      />,
    );

    expect(screen.getByText(/FAERS #S-1/i)).toBeInTheDocument();
  });

  it("prioritizes serious hospitalization reports and opens full report", () => {
    const onOpenEvidence = vi.fn();
    render(
      <EvidenceSpotlight
        activeQuarter="2023-Q3"
        evidence={reports}
        signalSnapshot={signalSnapshot}
        scorecard={scorecard}
        topSignal={signalSnapshot[1]}
        reinterpretedReportIds={[]}
        onOpenEvidence={onOpenEvidence}
      />,
    );

    expect(screen.getByText(/FAERS #S-2/i)).toBeInTheDocument();
    expect(screen.getByText(/validated signals/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /View full report/i }));
    expect(onOpenEvidence).toHaveBeenCalledWith("S-2");
  });

  it("shows reinterpretation message when selected report was reinterpreted", () => {
    render(
      <EvidenceSpotlight
        activeQuarter="2023-Q3"
        evidence={reports}
        signalSnapshot={signalSnapshot}
        scorecard={[]}
        topSignal={signalSnapshot[1]}
        reinterpretedReportIds={["S-2"]}
      />,
    );

    expect(screen.getByText(/retroactively reinterpreted/i)).toBeInTheDocument();
  });

  it("renders loading copy for focused auto evidence query", () => {
    render(
      <EvidenceSpotlight
        activeQuarter="2023-Q3"
        evidence={[]}
        signalSnapshot={signalSnapshot}
        scorecard={[]}
        topSignal={signalSnapshot[1]}
        loading
        focusEvent="Ileus"
      />,
    );

    expect(screen.getByText(/Loading report-level evidence for Ileus/i)).toBeInTheDocument();
  });

  it("renders configured empty message when no evidence is available", () => {
    render(
      <EvidenceSpotlight
        activeQuarter="2023-Q3"
        evidence={[]}
        signalSnapshot={signalSnapshot}
        scorecard={[]}
        topSignal={signalSnapshot[1]}
        emptyMessage="No report-level evidence found for this quarter yet."
      />,
    );

    expect(screen.getByText(/No report-level evidence found for this quarter yet/i)).toBeInTheDocument();
  });

  it("opens eventlog memory from provenance chip", () => {
    const onOpenEventLogMemory = vi.fn();
    render(
      <EvidenceSpotlight
        activeQuarter="2023-Q3"
        drugId="semaglutide"
        evidence={reports}
        signalSnapshot={signalSnapshot}
        scorecard={scorecard}
        topSignal={signalSnapshot[1]}
        reinterpretedReportIds={[]}
        showMemorySources
        onOpenEventLogMemory={onOpenEventLogMemory}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /vigl_semaglutide_S-2_eventlog/i }));
    expect(onOpenEventLogMemory).toHaveBeenCalledWith(
      "vigl_semaglutide_S-2_eventlog",
      expect.objectContaining({ safetyreportid: "S-2" }),
    );
  });
});
