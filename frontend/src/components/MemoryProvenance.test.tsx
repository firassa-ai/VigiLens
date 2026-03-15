import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MemoryProvenance } from "./MemoryProvenance";

describe("MemoryProvenance", () => {
  it("toggles memory source visibility", () => {
    const onToggle = vi.fn();
    render(
      <MemoryProvenance
        enabled={false}
        onToggle={onToggle}
        memoryStatusLabel="Memory-backed"
        memoryStatusTone="ok"
      />,
    );

    expect(screen.getByText(/Memory Diagnostics/i)).toBeInTheDocument();
    expect(screen.getByText(/Memory-backed/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Open provenance \+ diagnostics/i }));
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it("shows foresight status when enabled", () => {
    render(
      <MemoryProvenance
        enabled
        onToggle={vi.fn()}
        memoryStatusLabel="Memory degraded"
        memoryStatusTone="warning"
        foresightStatus={{
          status: "warning",
          message: "Foresight write failed ⚠️ Schema validation rejected one or more payloads.",
          total_predictions: 2,
          attempted_writes: 2,
          successful_writes: 1,
          failed_writes: 1,
          last_attempted_quarter: "2023-Q3",
        }}
      />,
    );

    expect(screen.getByText(/Foresight write failed/i)).toBeInTheDocument();
    expect(screen.getByText(/Memory degraded/i)).toBeInTheDocument();
    expect(screen.getByText(/Writes: 1\/2/i)).toBeInTheDocument();
    expect(screen.getByText(/Last quarter: 2023-Q3/i)).toBeInTheDocument();
  });
});
