import { afterEach, describe, expect, it } from "vitest";

import {
  clearPersistedRebuildJobId,
  persistRebuildJobId,
  readPersistedRebuildJobId,
} from "./rebuildJobs";

describe("rebuildJobs storage helpers", () => {
  afterEach(() => {
    window.sessionStorage.clear();
  });

  it("persists and restores a rebuild job id per drug", () => {
    persistRebuildJobId("minoxidil", "job-123");

    expect(readPersistedRebuildJobId("minoxidil")).toBe("job-123");
    expect(readPersistedRebuildJobId("semaglutide")).toBeNull();
  });

  it("clears a persisted rebuild job id", () => {
    persistRebuildJobId("minoxidil", "job-123");
    clearPersistedRebuildJobId("minoxidil");

    expect(readPersistedRebuildJobId("minoxidil")).toBeNull();
  });
});
