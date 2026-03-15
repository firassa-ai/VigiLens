import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AboutPanel } from "./AboutPanel";

describe("AboutPanel", () => {
  it("shows agent architecture copy with dynamic counts", () => {
    render(
      <AboutPanel
        reportsLoaded={2237}
        quartersLoaded={24}
        beliefCount={73}
        scorecardSummary="1 validated and 1 pending receipts"
        drugLabel="semaglutide"
        isPrimaryDemoDrug
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Show/i }));

    expect(screen.getByText(/memory-native pharmacovigilance agent/i)).toBeInTheDocument();
    expect(screen.getByText(/2,237 real FAERS reports across 24 quarters/i)).toBeInTheDocument();
    expect(screen.getByText(/EventLog: timestamped, citable FAERS report facts/i)).toBeInTheDocument();
    expect(screen.getByText(/Hierarchical memory flow/i)).toBeInTheDocument();
    expect(screen.getAllByText(/MemCells/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/MemScenes/i).length).toBeGreaterThan(0);
  });
});
