import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { Discover } from "./Discover";
import { useVigilensStore } from "../store/useVigilensStore";

const getDrugsMock = vi.fn();
const getCatalogSearchMock = vi.fn();
const getCatalogPreviewMock = vi.fn();
const deleteDrugMock = vi.fn();
const postTrackingJobMock = vi.fn();
const getTrackingJobMock = vi.fn();

vi.mock("../api/client", () => ({
  getDrugs: (...args: unknown[]) => getDrugsMock(...args),
  getCatalogSearch: (...args: unknown[]) => getCatalogSearchMock(...args),
  getCatalogPreview: (...args: unknown[]) => getCatalogPreviewMock(...args),
  deleteDrug: (...args: unknown[]) => deleteDrugMock(...args),
  postTrackingJob: (...args: unknown[]) => postTrackingJobMock(...args),
  getTrackingJob: (...args: unknown[]) => getTrackingJobMock(...args),
}));

vi.mock("../components/DrugSearchBar", () => ({
  DrugSearchBar: () => <div>search-bar</div>,
}));

vi.mock("../components/TrackedDrugList", () => ({
  TrackedDrugList: ({
    drugs,
    error,
    onDelete,
  }: {
    drugs: Array<{ id: string }>;
    error?: string | null;
    onDelete: (drugId: string) => Promise<boolean>;
  }) => (
    <div>
      <div>tracked-count:{drugs.length}</div>
      <div>tracked-error:{error ?? "none"}</div>
      {drugs.map((drug) => (
        <button key={drug.id} type="button" onClick={() => void onDelete(drug.id)}>
          delete-{drug.id}
        </button>
      ))}
    </div>
  ),
}));

vi.mock("../components/DrugSearchResults", () => ({
  DrugSearchResults: ({ query, onboarding }: { query: string; onboarding?: boolean }) => (
    <div>
      <div>results:{query}</div>
      <div>results-busy:{String(Boolean(onboarding))}</div>
    </div>
  ),
}));

vi.mock("../components/DrugPreviewPanel", () => ({
  DrugPreviewPanel: ({
    preview,
    candidateName,
    onboarding,
    onStartMonitoring,
  }: {
    preview: { generic_name: string } | null;
    candidateName: string | null;
    onboarding?: boolean;
    onStartMonitoring: () => void;
  }) => (
    <div>
      <div>preview:{preview?.generic_name ?? candidateName ?? "none"}</div>
      <div>preview-busy:{String(Boolean(onboarding))}</div>
      <button type="button" onClick={onStartMonitoring}>
        start-monitoring
      </button>
    </div>
  ),
}));

vi.mock("../components/TrackingProgress", () => ({
  TrackingProgress: ({
    job,
    error,
    onDismiss,
  }: {
    job: { status: string; step: string; drug_id: string | null } | null;
    error?: string | null;
    onDismiss?: () => void;
  }) => (
    <div>
      <div>tracking-status:{job?.status ?? "none"}</div>
      <div>tracking-step:{job?.step ?? "none"}</div>
      <div>tracking-error:{error ?? "none"}</div>
      {onDismiss ? (
        <button type="button" onClick={onDismiss}>
          dismiss-tracking
        </button>
      ) : null}
    </div>
  ),
}));

function renderDiscover(initialEntry: string) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/discover" element={<Discover />} />
        <Route path="/casefile/:drugId" element={<div>casefile-route</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("Discover tracking flow", () => {
  beforeEach(() => {
    useVigilensStore.setState({
      selectedDrugId: "semaglutide",
      drugs: [],
      ingestStatus: null,
      ingestProgress: null,
      timelinePoints: [],
      activeSignals: [],
      profile: null,
      episodes: [],
      fdaActions: [],
      beliefs: [],
      beliefDiff: null,
      scorecard: [],
      queryResponse: null,
      situationAnalysis: null,
      situationLoading: false,
      evidenceDrawerOpen: false,
      evidenceReportId: null,
      evidenceReport: null,
    });
    getDrugsMock.mockReset();
    getCatalogSearchMock.mockReset();
    getCatalogPreviewMock.mockReset();
    deleteDrugMock.mockReset();
    postTrackingJobMock.mockReset();
    getTrackingJobMock.mockReset();
  });

  it("starts a tracking job and redirects into the new casefile on success", async () => {
    getDrugsMock
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([
        {
          id: "clozapine",
          generic_name: "clozapine",
          brand_names: ["Clozaril"],
          total_reports: 500,
          quarters_loaded: ["2018-Q1"],
          next_quarter: "2018-Q2",
          current_profile_summary: "summary",
        },
      ]);
    getCatalogSearchMock.mockResolvedValue([
      {
        generic_name: "clozapine",
        brand_names: ["Clozaril"],
        tracked: false,
        tracked_drug_id: null,
        label_available: true,
        sources: ["dailymed", "faers"],
      },
    ]);
    getCatalogPreviewMock.mockResolvedValue({
      generic_name: "clozapine",
      brand_names: ["Clozaril"],
      tracked: false,
      tracked_drug_id: null,
      dailymed_setid: "set-1",
      dailymed_title: "CLOZARIL",
      dailymed_published_date: "Jun 30, 2025",
      faers_available: true,
    });
    postTrackingJobMock.mockResolvedValue({
      id: "job-1",
      status: "queued",
      step: "queued",
      progress: 0,
      medication_name: "clozapine",
      resolved_generic_name: null,
      drug_id: null,
      source: null,
      error: null,
      options_json: { baseline_quarters: 4, max_reports: 1500, prefer_cached: true },
      created_at: "2026-03-11T19:00:00Z",
      updated_at: "2026-03-11T19:00:00Z",
    });
    getTrackingJobMock.mockResolvedValue({
        id: "job-1",
        status: "ready",
        step: "ready",
        progress: 100,
        medication_name: "clozapine",
        resolved_generic_name: "clozapine",
        drug_id: "clozapine",
        source: "openfda",
        error: null,
        options_json: { baseline_quarters: 4, max_reports: 1500, prefer_cached: true },
        created_at: "2026-03-11T19:00:00Z",
        updated_at: "2026-03-11T19:00:02Z",
      });

    renderDiscover("/discover?q=clozapine&candidate=clozapine");

    expect(await screen.findByText("preview:clozapine")).toBeInTheDocument();

    fireEvent.click(screen.getByText("start-monitoring"));

    await waitFor(() => {
      expect(postTrackingJobMock).toHaveBeenCalledWith({
        medicationName: "clozapine",
        baselineQuarters: 4,
        maxReports: 1500,
        preferCached: true,
      });
    });

    expect(await screen.findByText("tracking-status:ready")).toBeInTheDocument();
    expect(await screen.findByText("casefile-route")).toBeInTheDocument();
    expect(useVigilensStore.getState().selectedDrugId).toBe("clozapine");
    expect(getTrackingJobMock).toHaveBeenCalled();
  });

  it("allows dismissing a failed job fetch back into preview mode", async () => {
    getDrugsMock.mockResolvedValue([]);
    getTrackingJobMock.mockRejectedValue(new Error("Tracking job unavailable"));

    renderDiscover("/discover?job=job-404");

    expect(await screen.findByText("tracking-error:Tracking job unavailable")).toBeInTheDocument();

    fireEvent.click(screen.getByText("dismiss-tracking"));

    await waitFor(() => {
      expect(screen.getByText("preview:none")).toBeInTheDocument();
    });
    expect(screen.queryByText("tracking-error:Tracking job unavailable")).not.toBeInTheDocument();
  });

  it("refreshes the tracked portfolio after deleting the selected drug", async () => {
    getDrugsMock
      .mockResolvedValueOnce([
        {
          id: "semaglutide",
          generic_name: "semaglutide",
          brand_names: ["Ozempic"],
          total_reports: 100,
          quarters_loaded: ["2018-Q1"],
          next_quarter: "2018-Q2",
          current_profile_summary: "summary",
        },
        {
          id: "metformin",
          generic_name: "metformin",
          brand_names: ["Glucophage"],
          total_reports: 1345,
          quarters_loaded: ["2018-Q1"],
          next_quarter: "2018-Q2",
          current_profile_summary: "summary",
        },
      ])
      .mockResolvedValueOnce([
        {
          id: "semaglutide",
          generic_name: "semaglutide",
          brand_names: ["Ozempic"],
          total_reports: 100,
          quarters_loaded: ["2018-Q1"],
          next_quarter: "2018-Q2",
          current_profile_summary: "summary",
        },
      ]);
    deleteDrugMock.mockResolvedValue({ drug_id: "metformin", deleted: true });

    useVigilensStore.setState({ selectedDrugId: "metformin" });

    renderDiscover("/discover");

    expect(await screen.findByText("tracked-count:2")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "delete-metformin" }));

    await waitFor(() => {
      expect(deleteDrugMock).toHaveBeenCalledWith("metformin");
    });
    await waitFor(() => {
      expect(screen.getByText("tracked-count:1")).toBeInTheDocument();
    });

    expect(screen.getByText("tracked-error:none")).toBeInTheDocument();
    expect(useVigilensStore.getState().selectedDrugId).toBe("semaglutide");
  });
});
