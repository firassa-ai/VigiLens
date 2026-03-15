import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DemoModeButton } from "./DemoModeButton";

describe("DemoModeButton", () => {
  it("triggers run handler when clicked", () => {
    const onRun = vi.fn(async () => undefined);
    render(<DemoModeButton stage="baseline" running={false} onRun={onRun} />);

    fireEvent.click(screen.getByRole("button", { name: /Run Demo/i }));
    expect(onRun).toHaveBeenCalledTimes(1);
  });

  it("shows stop label while running and remains clickable for interruption", () => {
    const onRun = vi.fn(async () => undefined);
    render(<DemoModeButton stage="reveal" running={true} onRun={onRun} />);

    fireEvent.click(screen.getByRole("button", { name: /Stop Demo/i }));
    expect(onRun).toHaveBeenCalledTimes(1);
  });

  it("surfaces staged labels for reveal and fast demo states", () => {
    const onRun = vi.fn(async () => undefined);
    const onFastDemo = vi.fn(async () => undefined);
    const { rerender } = render(
      <DemoModeButton
        stage="baseline"
        running={false}
        fastDemoReady
        onRun={onRun}
        onFastDemo={onFastDemo}
      />,
    );

    expect(screen.getByRole("button", { name: /Reveal reinterpretation/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Fast Demo/i }));
    expect(onFastDemo).toHaveBeenCalledTimes(1);

    rerender(<DemoModeButton stage="reveal" running={false} onRun={onRun} />);
    expect(screen.getByRole("button", { name: /Show FDA receipt/i })).toBeInTheDocument();
  });
});
