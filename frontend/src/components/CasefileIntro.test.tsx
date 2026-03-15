import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CasefileIntro } from "./CasefileIntro";

describe("CasefileIntro", () => {
  it("collapses long known-label lists behind a compact toggle", () => {
    render(
      <CasefileIntro
        drugLabel="minoxidil"
        brandNames={[
          "Rogaine",
          "Keeps",
          "Hims",
          "Foam Max",
          "Serum Plus",
          "Topical Restore",
          "Hair Bloom",
          "Growth Lab",
        ]}
        totalReports={500}
        activeQuarter="2018-Q2"
      />,
    );

    expect(screen.getByText("Rogaine")).toBeInTheDocument();
    expect(screen.getByText("Topical Restore")).toBeInTheDocument();
    expect(screen.queryByText("Hair Bloom")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "+2 more" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "+2 more" }));

    expect(screen.getByText("Hair Bloom")).toBeInTheDocument();
    expect(screen.getByText("Growth Lab")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show less" })).toBeInTheDocument();
  });

  it("renders the empty state when no labels are available", () => {
    render(
      <CasefileIntro
        drugLabel="minoxidil"
        brandNames={[]}
        totalReports={500}
        activeQuarter="2018-Q2"
      />,
    );

    expect(screen.getByText("No brand names captured yet.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /\+.*more/i })).not.toBeInTheDocument();
  });

  it("surfaces the full-history rebuild action in the header and calls the shared handler", async () => {
    const onRebuildFullHistory = vi.fn(async () => undefined);

    render(
      <CasefileIntro
        drugLabel="minoxidil"
        brandNames={["Rogaine"]}
        totalReports={500}
        activeQuarter="2018-Q2"
        onRebuildFullHistory={onRebuildFullHistory}
      />,
    );

    expect(screen.getByText(/500 suspect reports are loaded right now/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /download full history & rebuild/i }));
    expect(onRebuildFullHistory).toHaveBeenCalledTimes(1);
  });

  it("renders the generic casefile story summary with watchlist and label-gap cues", () => {
    render(
      <CasefileIntro
        drugLabel="minoxidil"
        brandNames={["Rogaine"]}
        totalReports={28236}
        activeQuarter="2023-Q4"
        casefileSummary={{
          drug_id: "minoxidil",
          viewed_quarter: "2023-Q4",
          stage: "escalation",
          headline: "Consensus signal strength is building around Systemic / Cardiovascular Warning.",
          summary:
            "minoxidil has moved past a quiet baseline. Systemic / Cardiovascular Warning now anchors the casefile.",
          lead_family: "Systemic / Cardiovascular Warning",
          lead_signal: {
            quarter: "2023-Q4",
            adverse_event: "Systemic / Cardiovascular Warning",
            report_count: 154,
            cumulative_count: 642,
            drug_total_cumulative: 28236,
            ror: 1.9,
            ror_ci_lower: 1.5,
            ror_ci_upper: 2.4,
            prr: 1.8,
            chi_squared: 12.4,
            signal_detected: true,
            trajectory: "accelerating",
            term_level: "family",
            consensus_tier: "public_signal",
            label_status: "label_gap",
            priority_flag: true,
            supporting_terms: ["Palpitations", "Dizziness"],
          },
          key_label_gaps: ["Hypersensitivity / Contact Dermatitis"],
          watchlist_alerts: [
            {
              quarter: "2023-Q4",
              adverse_event: "Hypersensitivity / Contact Dermatitis",
              report_count: 83,
              cumulative_count: 311,
              drug_total_cumulative: 28236,
              ror: 2.1,
              ror_ci_lower: 1.4,
              ror_ci_upper: 2.9,
              prr: 1.7,
              chi_squared: 9.1,
              signal_detected: true,
              trajectory: "emerging",
              term_level: "family",
              consensus_tier: "watchlist",
              label_status: "label_gap",
              priority_flag: false,
              supporting_terms: ["Hypersensitivity", "Contact dermatitis"],
            },
          ],
          public_forecasts: [
            {
              id: "forecast-1",
              drug_id: "minoxidil",
              adverse_event: "Systemic / Cardiovascular Warning",
              predicted_action: "warning",
              confidence: 74,
              predicted_date_range: ["2024-01-01", "2024-12-31"],
              created_at_quarter: "2023-Q4",
              visibility: "public",
              track: "proof",
              novelty_status: "known_label",
              evidence_grade: "moderate",
              trigger_basis: "label_gap_escalation",
              label_gap: true,
              basis: {
                type: "label_gap_escalation",
                summary: "Cardiovascular terms reached multi-method consensus and now outrun current label coverage.",
              },
              scope: {
                type: "drug",
                key: "minoxidil",
                label: "Minoxidil",
              },
              supporting_event: {
                adverse_event: "Systemic / Cardiovascular Warning",
                quarter: "2023-Q4",
                trajectory: "accelerating",
                cumulative_count: 642,
                evidence_report_ids: ["M-1001"],
                evidence_api_paths: ["/api/v1/evidence/M-1001"],
              },
              verification: {
                status: "supported",
                summary: "DailyMed labeling and recent external safety reporting support continued monitoring of systemic cardiovascular effects.",
                checked_at: "2026-03-12T08:00:00Z",
                queries: ["minoxidil palpitations dailymed"],
                citations: [
                  {
                    title: "DailyMed minoxidil label",
                    url: "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=minoxidil",
                    source_type: "dailymed",
                  },
                ],
                source_types: ["dailymed"],
              },
            },
          ],
          validated_receipts: 0,
          pending_receipts: 0,
          proof_backed_signals: 1,
          receipt_summary: "No regulatory receipts are linked yet.",
        }}
      />,
    );

    expect(screen.getByText(/Consensus signal strength is building around Systemic \/ Cardiovascular Warning/i)).toBeInTheDocument();
    expect(screen.getByText("Lead Family")).toBeInTheDocument();
    expect(screen.getAllByText("Systemic / Cardiovascular Warning").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Hypersensitivity / Contact Dermatitis").length).toBeGreaterThan(0);
    expect(screen.getByText(/No regulatory receipts are linked yet/i)).toBeInTheDocument();
    expect(screen.getByText(/Proof-backed Signal/i, { selector: "span" })).toBeInTheDocument();
    expect(screen.getByText("Proof-backed Signals", { selector: "p" })).toBeInTheDocument();
    expect(screen.getByText(/DailyMed labeling and recent external safety reporting/i)).toBeInTheDocument();
  });

  it("shows live rebuild progress and terminal status in the header callout", () => {
    const { rerender } = render(
      <CasefileIntro
        drugLabel="minoxidil"
        brandNames={["Rogaine"]}
        totalReports={500}
        activeQuarter="2018-Q2"
        onRebuildFullHistory={async () => undefined}
        fullHistoryJob={{
          id: "job-1",
          status: "running",
          step: "fetching_faers",
          progress: 41,
          medication_name: "minoxidil",
          resolved_generic_name: "minoxidil",
          drug_id: "minoxidil",
          source: null,
          error: null,
          options_json: {
            mode: "full_history_rebuild",
            drug_id: "minoxidil",
            baseline_quarters: 4,
            max_reports: null,
            prefer_cached: false,
          },
          details_json: {
            status_message: "Fetching month 31/72 (2020-07), page 2; 1,740 matched reports so far",
            window_index: 31,
            window_total: 72,
            pages_fetched: 2,
            matched_reports: 1740,
            provider_rows_seen: 2000,
          },
          created_at: "2026-03-11T20:00:00Z",
          updated_at: "2026-03-11T20:00:05Z",
        }}
      />,
    );

    expect(screen.getByText(/fetching full faers history/i)).toBeInTheDocument();
    expect(screen.getByText("41%")).toBeInTheDocument();
    expect(screen.getByText(/Fetching month 31\/72 \(2020-07\), page 2/i)).toBeInTheDocument();
    expect(screen.getByText("Matched: 1,740")).toBeInTheDocument();

    rerender(
      <CasefileIntro
        drugLabel="minoxidil"
        brandNames={["Rogaine"]}
        totalReports={500}
        activeQuarter="2018-Q2"
        onRebuildFullHistory={async () => undefined}
        fullHistoryJob={{
          id: "job-1",
          status: "ready",
          step: "ready",
          progress: 100,
          medication_name: "minoxidil",
          resolved_generic_name: "minoxidil",
          drug_id: "minoxidil",
          source: "openfda",
          error: null,
          options_json: {
            mode: "full_history_rebuild",
            drug_id: "minoxidil",
            baseline_quarters: 4,
            max_reports: null,
            prefer_cached: false,
          },
          created_at: "2026-03-11T20:00:00Z",
          updated_at: "2026-03-11T20:00:20Z",
        }}
      />,
    );

    expect(screen.getByText(/Full history loaded/i)).toBeInTheDocument();
  });
});
