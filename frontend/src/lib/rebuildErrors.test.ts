import { describe, expect, it } from "vitest";

import { ApiError } from "../api/client";
import { getRebuildPollError, getRebuildStartErrorMessage } from "./rebuildErrors";

describe("rebuildErrors", () => {
  it("maps a missing rebuild route to a backend restart message", () => {
    const error = new ApiError("Not Found", 404, null);

    expect(getRebuildStartErrorMessage(error)).toBe(
      "Full-history rebuild is unavailable on the running backend. Restart the backend server and try again.",
    );
  });

  it("maps a missing saved rebuild job to a retry message and clear signal", () => {
    const error = new ApiError("Tracking job was not found.", 404, {
      error: "NotFound",
      detail: "Tracking job was not found.",
      status_code: 404,
    });

    expect(getRebuildPollError(error)).toEqual({
      message: "Saved rebuild status was not found. Start the rebuild again.",
      clearPersistedJob: true,
    });
  });

  it("passes through non-special rebuild errors", () => {
    const error = new Error("Rate limit exceeded");

    expect(getRebuildStartErrorMessage(error)).toBe("Rate limit exceeded");
    expect(getRebuildPollError(error)).toEqual({
      message: "Rate limit exceeded",
      clearPersistedJob: false,
    });
  });
});
