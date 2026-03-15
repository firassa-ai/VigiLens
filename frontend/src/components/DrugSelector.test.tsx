import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DrugSelector } from "./DrugSelector";

describe("DrugSelector", () => {
  it("selects a tracked casefile", async () => {
    const onSelect = vi.fn();
    render(
      <DrugSelector
        drugs={[
          {
            id: "semaglutide",
            generic_name: "semaglutide",
            brand_names: ["Ozempic"],
            total_reports: 100,
            quarters_loaded: ["2018-Q1"],
            next_quarter: "2018-Q2",
            current_profile_summary: "summary",
          },
        ]}
        selectedDrugId="semaglutide"
        onSelect={onSelect}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /semaglutide/i }));

    expect(onSelect).toHaveBeenCalledWith("semaglutide");
  });

  it("collapses long alternative-name lists behind a compact toggle", () => {
    render(
      <DrugSelector
        drugs={[
          {
            id: "minoxidil",
            generic_name: "minoxidil",
            brand_names: ["Rogaine", "Keeps", "Hims", "Foam Max"],
            total_reports: 500,
            quarters_loaded: ["2018-Q1", "2018-Q2"],
            next_quarter: "2018-Q3",
            current_profile_summary: "summary",
          },
        ]}
        selectedDrugId="minoxidil"
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getByText("Rogaine / Keeps")).toBeInTheDocument();
    expect(screen.queryByText(/Foam Max/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "+2 more" }));

    expect(screen.getByText(/Rogaine \/ Keeps \/ Hims \/ Foam Max/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show less" })).toBeInTheDocument();
  });
});
