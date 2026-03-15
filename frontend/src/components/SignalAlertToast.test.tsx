import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { SignalPoint } from "../types/shared";
import { detectNewSignals, SignalAlertToast } from "./SignalAlertToast";

const previous: SignalPoint[] = [
  {
    quarter: "2023-Q2",
    adverse_event: "Ileus",
    report_count: 1,
    cumulative_count: 2,
    drug_total_cumulative: 18,
    ror: 0.9,
    ror_ci_lower: 0.4,
    ror_ci_upper: 1.5,
    prr: 1.0,
    chi_squared: 1.0,
    signal_detected: false,
    trajectory: "emerging",
  },
];

const current: SignalPoint[] = [
  {
    quarter: "2023-Q3",
    adverse_event: "Ileus",
    report_count: 9,
    cumulative_count: 9,
    drug_total_cumulative: 27,
    ror: 1.93,
    ror_ci_lower: 1.0,
    ror_ci_upper: 3.71,
    prr: 1.2,
    chi_squared: 4.2,
    signal_detected: true,
    trajectory: "emerging",
  },
];

describe("SignalAlertToast", () => {
  it("detects and renders new signal alerts", () => {
    const alerts = detectNewSignals(previous, current);
    expect(alerts).toHaveLength(1);
    expect(alerts[0].adverseEvent).toBe("Ileus");

    render(<SignalAlertToast toasts={alerts} />);
    expect(screen.getByText(/VigiLens Agent: New safety signal identified/i)).toBeInTheDocument();
    expect(screen.getByText(/Ileus shows disproportionate reporting/i)).toBeInTheDocument();
    expect(screen.getByText(/Quarter: 2023-Q3/i)).toBeInTheDocument();
  });
});
