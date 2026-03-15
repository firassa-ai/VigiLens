import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FirstLoadDemoEntrypoint } from "./FirstLoadDemoEntrypoint";

describe("FirstLoadDemoEntrypoint", () => {
  it("triggers start handler from the primary CTA", () => {
    const onStart = vi.fn(async () => undefined);
    render(
      <FirstLoadDemoEntrypoint
        drugLabel="Semaglutide"
        loading={false}
        starting={false}
        canStart
        nextQuarter="2018-Q2"
        onStart={onStart}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Prepare the Demo/i }));
    expect(onStart).toHaveBeenCalledTimes(1);
  });

  it("shows unavailable copy when start cannot run", () => {
    const onStart = vi.fn(async () => undefined);
    render(
      <FirstLoadDemoEntrypoint
        drugLabel="Semaglutide"
        loading={false}
        starting={false}
        canStart={false}
        nextQuarter={null}
        onStart={onStart}
      />,
    );

    expect(screen.getByText(/No additional quarters are available to process/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Prepare the Demo/i })).toBeDisabled();
  });
});
