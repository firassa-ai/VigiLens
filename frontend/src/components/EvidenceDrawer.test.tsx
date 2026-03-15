import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { EvidenceDrawer } from "./EvidenceDrawer";

function makeResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("EvidenceDrawer", () => {
  it("renders an initial cached report without waiting on fetch", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);

    render(
      <EvidenceDrawer
        open
        reportId="S-2023Q3A"
        initialReport={{
          safetyreportid: "S-2023Q3A",
          version: 1,
          receivedate: "2023-08-15",
          patient_sex: "male",
          patient_age: 57,
          reactions: ["Abdominal distension", "Constipation"],
          suspect_drugs: ["Semaglutide"],
          concomitant_drugs: [],
          serious: true,
          outcomes: ["Hospitalization"],
          evidence_api_path: "/api/v1/evidence/S-2023Q3A",
        }}
        onClose={() => undefined}
      />,
    );

    expect(screen.getByText("S-2023Q3A")).toBeInTheDocument();
    expect(screen.getByText(/Abdominal distension/i)).toBeInTheDocument();
    expect(screen.queryByText(/Loading/i)).not.toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("aborts stale request when report id changes", async () => {
    const abortSignals: AbortSignal[] = [];

    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        const signal = init?.signal as AbortSignal;
        abortSignals.push(signal);

        if (url.endsWith("/111")) {
          return new Promise<Response>((_resolve, reject) => {
            signal.addEventListener("abort", () => {
              reject(new DOMException("Aborted", "AbortError"));
            });
          });
        }

        return Promise.resolve(
          makeResponse({
            safetyreportid: "222",
            version: 1,
            receivedate: "2018-01-01",
            patient_sex: "unknown",
            patient_age: null,
            reactions: ["Nausea"],
            suspect_drugs: ["Semaglutide"],
            concomitant_drugs: ["DrugX"],
            serious: false,
            outcomes: [],
          }),
        );
      }),
    );

    const { rerender } = render(<EvidenceDrawer open reportId="111" onClose={() => undefined} />);

    rerender(<EvidenceDrawer open reportId="222" onClose={() => undefined} />);

    await waitFor(() => {
      expect(abortSignals.length).toBeGreaterThanOrEqual(2);
    });

    expect(abortSignals[0].aborted).toBe(true);
    expect(await screen.findByText(/Semaglutide/i)).toBeInTheDocument();
  });
});
