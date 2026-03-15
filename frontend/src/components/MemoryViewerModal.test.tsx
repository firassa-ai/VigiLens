import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MemoryViewerModal } from "./MemoryViewerModal";

describe("MemoryViewerModal", () => {
  it("renders memory details and closes", () => {
    const onClose = vi.fn();
    render(
      <MemoryViewerModal
        open
        onClose={onClose}
        entry={{
          id: "vigl_semaglutide_2023Q3_profile",
          type: "Profile",
          quarter: "2023-Q3",
          narrative: "Profile narrative",
          source: "EverMemOS Profile memory",
          metadata: [{ label: "Drug", value: "semaglutide" }],
        }}
      />,
    );

    expect(screen.getByRole("dialog", { name: /Memory Viewer/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Profile memory/i })).toBeInTheDocument();
    expect(screen.getByText(/Profile narrative/i)).toBeInTheDocument();
    expect(screen.getByText(/Drug:/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Close/i }));
    expect(onClose).toHaveBeenCalled();
  });
});
