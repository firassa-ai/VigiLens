import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { EpisodicTimeline } from "./EpisodicTimeline";

describe("EpisodicTimeline", () => {
  it("highlights current quarter and supports narrative expand/collapse", () => {
    render(
      <EpisodicTimeline
        loading={false}
        currentQuarter="2023-Q3"
        episodes={[
          {
            quarter: "2023-Q2",
            narrative: "Short narrative",
            key_signals_mentioned: ["Nausea"],
            report_count_ingested: 42,
            created_at: "2026-01-01T00:00:00Z",
            memory_source: "evermemos",
            memory_id: "mem-1",
          },
          {
            quarter: "2023-Q3",
            narrative:
              "Long narrative ".repeat(30),
            key_signals_mentioned: ["Constipation", "Ileus"],
            report_count_ingested: 87,
            created_at: "2026-01-01T00:00:00Z",
            memory_source: "evermemos",
            memory_id: "mem-2",
          },
        ]}
      />,
    );

    expect(screen.getByText("2023-Q3")).toBeInTheDocument();
    const showMore = screen.getByRole("button", { name: /show more/i });
    fireEvent.click(showMore);
    expect(screen.getByRole("button", { name: /show less/i })).toBeInTheDocument();
  });

  it("opens memory viewer when provenance memory id is clicked", () => {
    const onOpenMemory = vi.fn();
    render(
      <EpisodicTimeline
        loading={false}
        showMemorySources
        onOpenMemory={onOpenMemory}
        episodes={[
          {
            quarter: "2023-Q2",
            narrative: "Memory narrative",
            key_signals_mentioned: ["Ileus"],
            report_count_ingested: 20,
            created_at: "2026-01-01T00:00:00Z",
            memory_source: "evermemos",
            memory_id: "episodic-123",
          },
        ]}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /episodic-123/i }));
    expect(onOpenMemory).toHaveBeenCalledWith(
      expect.objectContaining({
        memory_id: "episodic-123",
        quarter: "2023-Q2",
      }),
    );
  });
});
