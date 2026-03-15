import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TrackedDrugList } from "./TrackedDrugList";

describe("TrackedDrugList", () => {
  it("collapses long brand-name lists behind a compact more affordance", () => {
    render(
      <TrackedDrugList
        drugs={[
          {
            id: "minoxidil",
            generic_name: "minoxidil",
            brand_names: ["Rogaine", "Keeps", "Hims", "Foam Max"],
            total_reports: 500,
            quarters_loaded: [],
            next_quarter: null,
            current_profile_summary: "summary",
          },
        ]}
        selectedDrugId={null}
        onOpen={vi.fn()}
        onDelete={vi.fn().mockResolvedValue(true)}
      />,
    );

    expect(screen.getByText("Rogaine / Keeps")).toBeInTheDocument();
    expect(screen.queryByText(/Foam Max/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "+2 more" }));

    expect(screen.getByText(/Rogaine \/ Keeps \/ Hims \/ Foam Max/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show less" })).toBeInTheDocument();
  });

  it("requires confirmation before deleting a tracked drug", async () => {
    const onDelete = vi.fn().mockResolvedValue(true);

    render(
      <TrackedDrugList
        drugs={[
          {
            id: "metformin",
            generic_name: "metformin",
            brand_names: ["Glucophage"],
            total_reports: 1345,
            quarters_loaded: ["2018-Q1"],
            next_quarter: "2018-Q2",
            current_profile_summary: "summary",
          },
        ]}
        selectedDrugId="metformin"
        onOpen={vi.fn()}
        onDelete={onDelete}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    expect(
      screen.getByText((_content, node) => node?.textContent === "Remove metformin from tracked casefiles?"),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Confirm delete" }));

    await waitFor(() => {
      expect(onDelete).toHaveBeenCalledWith("metformin");
    });
  });
});
