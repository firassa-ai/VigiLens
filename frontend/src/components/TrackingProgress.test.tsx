import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TrackingProgress } from "./TrackingProgress";

describe("TrackingProgress", () => {
  it("renders granular fetch details for a running tracking job", () => {
    render(
      <TrackingProgress
        job={{
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
          created_at: "2026-03-12T08:00:00Z",
          updated_at: "2026-03-12T08:04:00Z",
        }}
      />,
    );

    expect(screen.getByText(/Fetching month 31\/72 \(2020-07\), page 2/i)).toBeInTheDocument();
    expect(screen.getByText("Month: 31/72")).toBeInTheDocument();
    expect(screen.getByText("Pages: 2")).toBeInTheDocument();
    expect(screen.getByText("Matched: 1,740")).toBeInTheDocument();
    expect(screen.getByText("Rows seen: 2,000")).toBeInTheDocument();
  });
});
