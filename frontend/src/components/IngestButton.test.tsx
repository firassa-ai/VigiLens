import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { IngestButton } from "./IngestButton";

describe("IngestButton", () => {
  it("calls onIngest when enabled", async () => {
    const onIngest = vi.fn(async () => undefined);
    const onIngestAll = vi.fn(async () => undefined);
    const onRebuildFullHistory = vi.fn(async () => undefined);
    render(
      <IngestButton
        status={{
          drug_id: "semaglutide",
          quarters_loaded: ["2018-Q1"],
          next_quarter: "2018-Q2",
          total_reports_loaded: 100,
          evermemos_status: "ready",
        }}
        storedReportCount={500}
        onIngest={onIngest}
        onIngestAll={onIngestAll}
        onRebuildFullHistory={onRebuildFullHistory}
        onReset={async () => undefined}
        progress={null}
      />,
    );

    const button = screen.getByRole("button", { name: /advance q2 2018/i });
    await userEvent.click(button);
    expect(onIngest).toHaveBeenCalledTimes(1);
  });

  it("calls onIngestAll when enabled", async () => {
    const onIngest = vi.fn(async () => undefined);
    const onIngestAll = vi.fn(async () => undefined);
    const onRebuildFullHistory = vi.fn(async () => undefined);
    render(
      <IngestButton
        status={{
          drug_id: "semaglutide",
          quarters_loaded: ["2018-Q1"],
          next_quarter: "2018-Q2",
          total_reports_loaded: 100,
          evermemos_status: "ready",
        }}
        storedReportCount={500}
        onIngest={onIngest}
        onIngestAll={onIngestAll}
        onRebuildFullHistory={onRebuildFullHistory}
        onReset={async () => undefined}
        progress={null}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: /run full simulation/i }));
    expect(onIngestAll).toHaveBeenCalledTimes(1);
  });

  it("shows live progress and disables action while running", () => {
    render(
      <IngestButton
        status={{
          drug_id: "semaglutide",
          quarters_loaded: ["2018-Q1"],
          next_quarter: "2018-Q2",
          total_reports_loaded: 100,
          evermemos_status: "ready",
        }}
        storedReportCount={500}
        onIngest={async () => undefined}
        onIngestAll={async () => undefined}
        onRebuildFullHistory={async () => undefined}
        onReset={async () => undefined}
        progress={{
          phase: "computing_signals",
          quarter: "2018-Q2",
          reports_processed: 32,
          total_reports: 100,
          signals_updated: 10,
          evermemos_consolidation_status: "idle",
        }}
      />,
    );

    expect(screen.getByText(/computing ror\/prr trajectories/i)).toBeInTheDocument();
    expect(screen.getByText("32/100")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /advance q2 2018/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /run full simulation/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /download full history/i })).toBeDisabled();
  });

  it("renders ingest-all quarter counter when active", () => {
    render(
      <IngestButton
        status={{
          drug_id: "semaglutide",
          quarters_loaded: ["2018-Q1", "2018-Q2"],
          next_quarter: "2018-Q3",
          total_reports_loaded: 200,
          total_quarters_available: 24,
          evermemos_status: "ready",
        }}
        storedReportCount={500}
        onIngest={async () => undefined}
        onIngestAll={async () => undefined}
        onRebuildFullHistory={async () => undefined}
        onReset={async () => undefined}
        progress={null}
        ingestAllProgress={{ active: true, completedQuarters: 4, totalQuarters: 20 }}
      />,
    );

    expect(screen.getByText(/Simulation progress: 4\/20 quarters/i)).toBeInTheDocument();
  });

  it("calls the full-history rebuild action when requested", async () => {
    const onRebuildFullHistory = vi.fn(async () => undefined);

    render(
      <IngestButton
        status={{
          drug_id: "minoxidil",
          quarters_loaded: ["2018-Q1", "2018-Q2"],
          next_quarter: "2018-Q3",
          total_reports_loaded: 220,
          total_quarters_available: 24,
          evermemos_status: "ready",
        }}
        storedReportCount={500}
        onIngest={async () => undefined}
        onIngestAll={async () => undefined}
        onRebuildFullHistory={onRebuildFullHistory}
        onReset={async () => undefined}
        progress={null}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: /download full history & rebuild/i }));
    expect(onRebuildFullHistory).toHaveBeenCalledTimes(1);
  });

  it("shows full-history rebuild progress when a rebuild job is active", () => {
    render(
      <IngestButton
        status={{
          drug_id: "minoxidil",
          quarters_loaded: ["2018-Q1", "2018-Q2"],
          next_quarter: "2018-Q3",
          total_reports_loaded: 220,
          total_quarters_available: 24,
          evermemos_status: "ready",
        }}
        storedReportCount={500}
        onIngest={async () => undefined}
        onIngestAll={async () => undefined}
        onRebuildFullHistory={async () => undefined}
        onReset={async () => undefined}
        progress={null}
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
  });

  it("allows dismissing terminal rebuild status", async () => {
    const onDismissFullHistory = vi.fn();

    render(
      <IngestButton
        status={{
          drug_id: "minoxidil",
          quarters_loaded: ["2018-Q1", "2018-Q2"],
          next_quarter: "2018-Q3",
          total_reports_loaded: 220,
          total_quarters_available: 24,
          evermemos_status: "ready",
        }}
        storedReportCount={500}
        onIngest={async () => undefined}
        onIngestAll={async () => undefined}
        onRebuildFullHistory={async () => undefined}
        onDismissFullHistory={onDismissFullHistory}
        onReset={async () => undefined}
        progress={null}
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
          updated_at: "2026-03-11T20:00:05Z",
        }}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: /dismiss rebuild status/i }));
    expect(onDismissFullHistory).toHaveBeenCalledTimes(1);
  });
});
