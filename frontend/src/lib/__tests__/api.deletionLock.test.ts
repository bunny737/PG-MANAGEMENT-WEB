import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { DELETION_PENDING_ROUTE } from "../accountDeletion";

function respond(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

/** jsdom's window.location is read-only; swap it for a plain object we can inspect. */
function stubLocation(pathname: string) {
  const location = { pathname, href: pathname };
  vi.stubGlobal("location", location);
  return location;
}

// An account scheduled for deletion is locked: the API answers 403 with a deletion code on every route
// but the status/cancel ones. That is NOT a dead session, so it must not log the user out the way a
// 401 does, and it must not look like "an Owner changed my access" either.
describe("apiFetch and a locked account", () => {
  beforeEach(() => {
    localStorage.setItem("isLoggedIn", "true");
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.resetModules();
    localStorage.clear();
  });

  test.each(["ACCOUNT_DELETION_PENDING", "TENANT_DELETION_PENDING"])(
    "a 403 %s keeps the session and goes to the pending screen",
    async (code) => {
      const location = stubLocation("/dashboard");
      vi.stubGlobal("fetch", vi.fn(async () => respond(403, { detail: "locked", code })));
      const permissionDenied = vi.fn();
      window.addEventListener("permission-denied", permissionDenied);

      const { apiFetch, ApiError } = await import("../api");
      await expect(apiFetch("/api/v1/properties/")).rejects.toBeInstanceOf(ApiError);

      expect(location.href).toBe(DELETION_PENDING_ROUTE);
      expect(localStorage.getItem("isLoggedIn")).toBe("true"); // session untouched
      expect(permissionDenied).not.toHaveBeenCalled();
      window.removeEventListener("permission-denied", permissionDenied);
    }
  );

  test("on the pending screen itself it does not redirect again (no loop)", async () => {
    const location = stubLocation(DELETION_PENDING_ROUTE);
    vi.stubGlobal("fetch", vi.fn(async () => respond(403, { code: "ACCOUNT_DELETION_PENDING" })));

    const { apiFetch } = await import("../api");
    await expect(apiFetch("/api/v1/properties/")).rejects.toMatchObject({ status: 403 });

    expect(location.href).toBe(DELETION_PENDING_ROUTE);
    expect(location.href).toBe(location.pathname);
  });

  test("an ordinary 403 still refreshes permissions and never redirects", async () => {
    const location = stubLocation("/dashboard");
    vi.stubGlobal("fetch", vi.fn(async () => respond(403, { detail: "no", code: "PERMISSION_DENIED" })));
    const permissionDenied = vi.fn();
    window.addEventListener("permission-denied", permissionDenied);

    const { apiFetch } = await import("../api");
    await expect(apiFetch("/api/v1/properties/")).rejects.toMatchObject({ status: 403 });

    expect(permissionDenied).toHaveBeenCalledTimes(1);
    expect(location.href).toBe("/dashboard");
    window.removeEventListener("permission-denied", permissionDenied);
  });

  test("a 401 is still a dead session", async () => {
    const location = stubLocation("/dashboard");
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request) =>
        String(input).includes("/api/auth/logout") ? new Response(null, { status: 204 }) : respond(401, {})
      )
    );

    const { apiFetch } = await import("../api");
    await expect(apiFetch("/api/v1/properties/")).rejects.toMatchObject({ status: 401 });

    expect(location.href).toBe("/login");
    expect(localStorage.getItem("isLoggedIn")).toBeNull();
  });
});
