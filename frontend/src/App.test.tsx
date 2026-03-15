import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { useVigilensStore } from "./store/useVigilensStore";

const getDrugsMock = vi.fn();

vi.mock("./api/client", () => ({
  getDrugs: (...args: unknown[]) => getDrugsMock(...args),
}));

vi.mock("./pages/Discover", () => ({
  Discover: () => <div>discover-surface</div>,
}));

vi.mock("./pages/Dashboard", () => ({
  Dashboard: () => <div>casefile-surface</div>,
}));

vi.mock("./components/Sidebar", () => ({
  Sidebar: () => <div>casefile-sidebar</div>,
}));

vi.mock("./components/SurfaceNav", () => ({
  SurfaceNav: () => <div>surface-nav</div>,
}));

describe("App routing", () => {
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
  });

  afterEach(() => {
    window.history.pushState({}, "", "/");
  });

  it("defaults to the discover surface", async () => {
    window.history.pushState({}, "", "/");

    render(<App />);

    expect(await screen.findByText("discover-surface")).toBeInTheDocument();
    expect(screen.getByText("surface-nav")).toBeInTheDocument();
  });

  it("opens a casefile route and shows the casefile chrome", async () => {
    window.history.pushState({}, "", "/casefile/semaglutide");
    getDrugsMock.mockResolvedValue([
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

    render(<App />);

    expect(screen.getByText("surface-nav")).toBeInTheDocument();
    expect(screen.getByText("casefile-sidebar")).toBeInTheDocument();
    expect(await screen.findByText("casefile-surface")).toBeInTheDocument();

    await waitFor(() => {
      expect(window.location.pathname).toBe("/casefile/semaglutide");
    });
  });

  it("refetches the tracked drugs when the requested casefile is missing from stale store data", async () => {
    window.history.pushState({}, "", "/casefile/clozapine");
    useVigilensStore.setState((state) => ({
      ...state,
      selectedDrugId: "metformin",
      drugs: [
        {
          id: "metformin",
          generic_name: "metformin",
          brand_names: ["Glucophage"],
          total_reports: 80,
          quarters_loaded: ["2018-Q1"],
          next_quarter: "2018-Q2",
          current_profile_summary: "summary",
        },
      ],
    }));
    getDrugsMock.mockResolvedValue([
      {
        id: "metformin",
        generic_name: "metformin",
        brand_names: ["Glucophage"],
        total_reports: 80,
        quarters_loaded: ["2018-Q1"],
        next_quarter: "2018-Q2",
        current_profile_summary: "summary",
      },
      {
        id: "clozapine",
        generic_name: "clozapine",
        brand_names: ["Clozaril"],
        total_reports: 120,
        quarters_loaded: ["2018-Q1"],
        next_quarter: "2018-Q2",
        current_profile_summary: "summary",
      },
    ]);

    render(<App />);

    expect(await screen.findByText("casefile-surface")).toBeInTheDocument();
    await waitFor(() => {
      expect(window.location.pathname).toBe("/casefile/clozapine");
    });
    expect(useVigilensStore.getState().selectedDrugId).toBe("clozapine");
  });
});
