import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, getHealth } from "./client";

function response(payload: unknown, status: number): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("api client retry behavior", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("retries once for 5xx", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response({ error: "ServerError", detail: "boom", status_code: 500 }, 500))
      .mockResolvedValueOnce(
        response(
          {
            ok: true,
            postgres_ok: true,
            evermemos_ok: true,
            evermemos_version: "unknown",
            timestamp: "2026-02-21T00:00:00Z",
          },
          200,
        ),
      );

    vi.stubGlobal("fetch", fetchMock);

    const payload = await getHealth();
    expect(payload.ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("does not retry for 4xx", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      response({ error: "BadRequest", detail: "invalid", status_code: 400 }, 400),
    );

    vi.stubGlobal("fetch", fetchMock);

    await expect(getHealth()).rejects.toBeInstanceOf(ApiError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("does not retry aborted requests", async () => {
    const abortedError = new Error("Aborted");
    abortedError.name = "AbortError";
    const fetchMock = vi.fn().mockRejectedValueOnce(abortedError);

    vi.stubGlobal("fetch", fetchMock);

    await expect(getHealth()).rejects.toMatchObject({ name: "AbortError" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("dedupes concurrent identical GET requests", async () => {
    let resolveFetch: ((value: Response) => void) | null = null;
    const fetchMock = vi.fn().mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          resolveFetch = resolve;
        }),
    );

    vi.stubGlobal("fetch", fetchMock);

    const firstRequest = getHealth();
    const secondRequest = getHealth();

    expect(fetchMock).toHaveBeenCalledTimes(1);

    expect(resolveFetch).not.toBeNull();
    resolveFetch!(
      response(
        {
          ok: true,
          postgres_ok: true,
          evermemos_ok: true,
          evermemos_version: "unknown",
          timestamp: "2026-02-21T00:00:00Z",
        },
        200,
      ),
    );

    const [firstPayload, secondPayload] = await Promise.all([firstRequest, secondRequest]);
    expect(firstPayload).toEqual(secondPayload);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
