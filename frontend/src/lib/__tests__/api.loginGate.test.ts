import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { registerSessionCleanup, runSessionCleanups } from "../sessionPurge";

// Covers the plan's "a second login started during a slow purge does not
// store tokens until the purge finishes" case: login()/loginPhone() await
// awaitPendingPurge() before ever calling fetch, so a purge started by a
// race (e.g. a 401 on an in-flight request) can't be undone by the tokens
// a fresh login is about to store.
describe("login gate (awaitPendingPurge)", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  test("login() does not store tokens until a pending purge resolves", async () => {
    let resolvePurgeStep: () => void = () => {};
    const unregister = registerSessionCleanup(
      () =>
        new Promise<void>((resolve) => {
          resolvePurgeStep = resolve;
        })
    );
    const purge = runSessionCleanups();

    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = String(input);
      if (url.includes("/auth/login/")) {
        return new Response(JSON.stringify({ access: "new-access", refresh: "new-refresh" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.includes("/auth/me/")) {
        return new Response(
          JSON.stringify({
            id: "user-1",
            email: "owner@example.com",
            role: "owner",
            language_code: "en",
            email_verified: true,
            permissions: [],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const { login } = await import("../api");
    const loginPromise = login("owner@example.com", "secret");

    // The purge is still pending: login() must not have reached fetch yet.
    await Promise.resolve();
    await Promise.resolve();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(localStorage.getItem("accessToken")).toBeNull();

    resolvePurgeStep();
    await purge;
    await loginPromise;

    expect(fetchMock).toHaveBeenCalled();
    expect(localStorage.getItem("accessToken")).toBe("new-access");
    unregister();
  });
});
