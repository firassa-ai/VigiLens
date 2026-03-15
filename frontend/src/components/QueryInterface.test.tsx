import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { QueryInterface } from "./QueryInterface";

const baseResponse = {
  answer_text: "answer",
  confidence: 70,
  signal_summary: [],
  evidence: [],
  episodic_context: [],
  belief_id: "b1",
  foresight_memory_ids: [],
};

describe("QueryInterface", () => {
  it("submits on click when quarter is loaded", async () => {
    const onSubmit = vi.fn(async () => undefined);

    render(
      <QueryInterface
        drugId="semaglutide"
        activeQuarter="2023-Q4"
        onSubmit={onSubmit}
        response={null}
        loading={false}
      />,
    );

    await userEvent.type(screen.getByPlaceholderText(/are gi motility risks emerging\?/i), "How is GI trend?");
    await userEvent.click(screen.getByRole("button", { name: /ask/i }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith("How is GI trend?");
  });

  it("submits on Enter when quarter is loaded", async () => {
    const onSubmit = vi.fn(async () => undefined);

    render(
      <QueryInterface
        drugId="semaglutide"
        activeQuarter="2023-Q4"
        onSubmit={onSubmit}
        response={baseResponse}
        loading={false}
      />,
    );

    const input = screen.getByPlaceholderText(/are gi motility risks emerging\?/i);
    await userEvent.type(input, "Enter path works{enter}");

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith("Enter path works");
  });

  it("disables querying when no quarter is loaded", async () => {
    const onSubmit = vi.fn(async () => undefined);

    render(
      <QueryInterface
        drugId="semaglutide"
        activeQuarter={null}
        onSubmit={onSubmit}
        response={null}
        loading={false}
      />,
    );

    const input = screen.getByPlaceholderText(/are gi motility risks emerging\?/i);
    const button = screen.getByRole("button", { name: /ask/i });

    expect(button).toBeDisabled();
    expect(screen.getByText(/load at least one quarter before running a query/i)).toBeInTheDocument();

    await userEvent.type(input, "Should not send{enter}");
    await userEvent.click(button);

    expect(onSubmit).not.toHaveBeenCalled();
  });
});
