import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { getCacheScope } from "../cacheScope";
import { isMarketingPath } from "../marketingPaths";
import { queryClient } from "../queryClient";
import { runSessionCleanups } from "../sessionPurge";

describe("offline rules (docs/frontend-plan.md §5.1)", () => {
  test("mutations are never paused and replayed after reconnect", () => {
    // TanStack's default ("online") queues a mutation made offline and replays it on
    // reconnect: an implicit offline write queue for payments, which the plan forbids.
    expect(queryClient.getDefaultOptions().mutations?.networkMode).toBe("always");
  });

  test("queries still attempt a fetch offline so the service worker's cached reads are reachable", () => {
    expect(queryClient.getDefaultOptions().queries?.networkMode).toBe("offlineFirst");
  });
});

describe("cache scope (invariant F7 for the service worker's API cache)", () => {
  beforeEach(() => localStorage.clear());

  test("is tenant + user, so two users never share a cache", () => {
    localStorage.setItem("currentUser", JSON.stringify({ id: "u1", tenant_id: "t1" }));
    const first = getCacheScope();
    localStorage.setItem("currentUser", JSON.stringify({ id: "u2", tenant_id: "t1" }));
    expect(first).toBe("t1_u1");
    expect(getCacheScope()).toBe("t1_u2");
  });

  test("falls back to the nested tenant id", () => {
    localStorage.setItem("currentUser", JSON.stringify({ id: "u1", tenant: { id: "t9" } }));
    expect(getCacheScope()).toBe("t9_u1");
  });

  test("is null with no session or unreadable state, so nothing gets cached", () => {
    expect(getCacheScope()).toBeNull();
    localStorage.setItem("currentUser", "{not json");
    expect(getCacheScope()).toBeNull();
    localStorage.setItem("currentUser", JSON.stringify({ tenant_id: "t1" }));
    expect(getCacheScope()).toBeNull();
  });
});

describe("session purge vs Cache Storage", () => {
  afterEach(() => vi.unstubAllGlobals());

  test("deletes tenant-bearing caches but keeps the build-output ones so the shell opens offline", async () => {
    const existing = new Set([
      "serwist-precache-v2-https://app.example/",
      "next-static",
      "app-images",
      "api-t1_u1",
      "pages",
      "something-unknown",
    ]);
    vi.stubGlobal("caches", {
      keys: async () => [...existing],
      delete: async (name: string) => existing.delete(name),
    });

    await runSessionCleanups();

    expect([...existing].sort()).toEqual(
      ["app-images", "next-static", "serwist-precache-v2-https://app.example/"].sort()
    );
  });
});

describe("marketing pages stay out of the worker's page cache", () => {
  test.each([
    "/",
    "/features",
    "/pricing",
    "/app",
    "/contact",
    "/privacy",
    "/terms",
    "/refund-policy",
    "/pricing/",
    "/features/x",
  ])(
    "%s is a marketing path",
    (path) => expect(isMarketingPath(path)).toBe(true)
  );

  test.each(["/login", "/dashboard", "/more", "/approval", "/applications", "/~offline", "/pricingx"])(
    "%s is part of the installed app",
    (path) => expect(isMarketingPath(path)).toBe(false)
  );
});
