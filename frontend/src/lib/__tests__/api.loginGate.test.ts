import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { registerSessionCleanup, runSessionCleanups } from "../sessionPurge";

// Covers the plan's "a second login started during a slow purge does not
// sign in until the purge finishes" case: login()/loginPhone() await
// awaitPendingPurge() before ever calling fetch, so a purge started by a
// race (e.g. a 401 on an in-flight request, whose step also clears the auth
// cookies) can't be undone by the cookies a fresh login is about to set.
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
      if (url.includes("/api/auth/login")) {
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
    expect(localStorage.getItem("isLoggedIn")).toBeNull();

    resolvePurgeStep();
    await purge;
    await loginPromise;

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toBe("/api/auth/login");
    expect(localStorage.getItem("isLoggedIn")).toBe("true");
    // No JWT ever lands in page-accessible storage.
    expect(localStorage.getItem("accessToken")).toBeNull();
    expect(localStorage.getItem("refreshToken")).toBeNull();
    unregister();
  });
});
