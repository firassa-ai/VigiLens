import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ProfileCard } from "./ProfileCard";

describe("ProfileCard", () => {
  it("shows EverMemOS provenance when enabled", () => {
    render(
      <ProfileCard
        loading={false}
        showMemorySources
        memoryUpdatedQuarter="2023-Q3"
        memoryId="vigl_semaglutide_2023Q3_profile"
        profile={{
          drug_id: "semaglutide",
          current_assessment: "Assessment",
          risk_level: "elevated",
          known_signals: ["Constipation"],
          investigating_signals: ["Ileus"],
          last_updated: "2026-02-21T00:00:00Z",
        }}
      />,
    );

    expect(screen.getByText(/Profile stored in EverMemOS/i)).toBeInTheDocument();
    expect(screen.getByText(/Last updated: 2023-Q3/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /vigl_semaglutide_2023Q3_profile/i })).toBeInTheDocument();
  });

  it("calls onOpenMemory when profile memory id is clicked", () => {
    const onOpenMemory = vi.fn();
    render(
      <ProfileCard
        loading={false}
        showMemorySources
        memoryUpdatedQuarter="2023-Q3"
        memoryId="vigl_semaglutide_2023Q3_profile"
        onOpenMemory={onOpenMemory}
        profile={{
          drug_id: "semaglutide",
          current_assessment: "Assessment",
          risk_level: "elevated",
          known_signals: ["Constipation"],
          investigating_signals: ["Ileus"],
          last_updated: "2026-02-21T00:00:00Z",
        }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /vigl_semaglutide_2023Q3_profile/i }));
    expect(onOpenMemory).toHaveBeenCalled();
  });
});
