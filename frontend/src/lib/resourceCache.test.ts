import { describe, expect, it, vi } from "vitest";

import {
  clearCachedResource,
  getCachedResource,
  seedCachedResource,
} from "./resourceCache";

describe("resourceCache", () => {
  it("deduplicates concurrent requests for the same key", async () => {
    const cache = new Map<string, number>();
    const inFlight = new Map<string, Promise<number>>();
    const loader = vi.fn(async () => 42);

    const [first, second] = await Promise.all([
      getCachedResource("same", cache, inFlight, loader),
      getCachedResource("same", cache, inFlight, loader),
    ]);

    expect(first).toBe(42);
    expect(second).toBe(42);
    expect(loader).toHaveBeenCalledTimes(1);
    expect(cache.get("same")).toBe(42);
    expect(inFlight.size).toBe(0);
  });

  it("returns seeded values without calling the loader", async () => {
    const cache = new Map<string, string>();
    const inFlight = new Map<string, Promise<string>>();
    const loader = vi.fn(async () => "network");

    seedCachedResource("seeded", cache, "cached");
    const value = await getCachedResource("seeded", cache, inFlight, loader);

    expect(value).toBe("cached");
    expect(loader).not.toHaveBeenCalled();
  });

  it("clears cached and pending entries", () => {
    const cache = new Map<string, string>([["a", "value"]]);
    const inFlight = new Map<string, Promise<string>>([
      ["a", Promise.resolve("value")],
    ]);

    clearCachedResource(cache, inFlight);

    expect(cache.size).toBe(0);
    expect(inFlight.size).toBe(0);
  });
});
