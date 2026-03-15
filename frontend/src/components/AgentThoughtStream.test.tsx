import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AgentThoughtStream, type AgentLogEntry } from "./AgentThoughtStream";

const baseEntries: AgentLogEntry[] = [
  {
    id: "thought-1",
    type: "memory_recall",
    content: "Retrieved 2 episodic memories for grounding.",
    timestamp: "2026-02-23T10:00:00Z",
    memoryRefs: ["episodic:sema:2023-Q2"],
    metadata: {
      memory_preview: {
        "episodic:sema:2023-Q2": "Sample memory preview",
      },
    },
  },
];

describe("AgentThoughtStream", () => {
  it("renders entries and hides memory chips when Memory Sources is off", () => {
    render(
      <AgentThoughtStream entries={baseEntries} runState="running" showMemorySources={false} />,
    );

    expect(screen.getByText(/Agent Activity/i)).toBeInTheDocument();
    expect(screen.getByText(/Retrieved 2 episodic memories/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /episodic:sema:2023-Q2/i })).not.toBeInTheDocument();
  });

  it("shows memory chips and opens callback when clicked", () => {
    const onOpenMemoryRef = vi.fn();
    render(
      <AgentThoughtStream
        entries={baseEntries}
        runState="running"
        showMemorySources
        onOpenMemoryRef={onOpenMemoryRef}
      />,
    );

    const chip = screen.getByRole("button", { name: /episodic:sema:2023-Q2/i });
    fireEvent.click(chip);
    expect(onOpenMemoryRef).toHaveBeenCalledWith(
      "episodic:sema:2023-Q2",
      expect.objectContaining({ id: "thought-1" }),
    );
  });

  it("pulses border for reinterpretation and clears after timer", () => {
    vi.useFakeTimers();
    const reinterpretationEntry: AgentLogEntry = {
      id: "thought-2",
      type: "reinterpretation",
      content: "Retroactive reinterpretation triggered.",
      timestamp: "2026-02-23T10:01:00Z",
    };

    const { container } = render(
      <AgentThoughtStream
        entries={[...baseEntries, reinterpretationEntry]}
        runState="running"
        showMemorySources={false}
      />,
    );

    expect(container.firstChild).toHaveClass("border-red-400/60");
    vi.useRealTimers();
  });

  it("cleans pending timers on unmount", () => {
    vi.useFakeTimers();
    const reinterpretationEntry: AgentLogEntry = {
      id: "thought-3",
      type: "reinterpretation",
      content: "Retroactive reinterpretation triggered.",
      timestamp: "2026-02-23T10:02:00Z",
    };

    const view = render(
      <AgentThoughtStream
        entries={[...baseEntries, reinterpretationEntry]}
        runState="running"
        showMemorySources={false}
      />,
    );

    view.unmount();
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
  });

  it("shows MONITORING status when idle and uses larger viewport", () => {
    const { container } = render(
      <AgentThoughtStream entries={[]} runState="idle" showMemorySources={false} />,
    );

    expect(screen.getByText("MONITORING")).toBeInTheDocument();
    const viewport = container.querySelector("div.h-\\[320px\\]");
    expect(viewport).toBeTruthy();
  });
});
