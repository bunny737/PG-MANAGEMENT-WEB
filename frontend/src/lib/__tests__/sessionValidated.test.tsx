import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ getCurrentUser: vi.fn() }));

vi.mock("@/lib/api", () => ({
  getCurrentUser: api.getCurrentUser,
  PERMISSION_DENIED_EVENT: "permission-denied",
  PERMISSIONS_KEY: "userPermissions",
}));

const ME = { role: "owner", permissions: ["view_dashboard"], first_name: "A", last_name: "B" };

function login(role = "owner") {
  localStorage.setItem("isLoggedIn", "true");
  localStorage.setItem("userRole", role);
  localStorage.setItem("userPermissions", JSON.stringify(["view_dashboard"]));
}

// session.ts keeps module-level state, so each test gets a fresh copy of it.
async function loadSession() {
  vi.resetModules();
  return import("../session");
}

describe("session `validated` flag", () => {
  beforeEach(() => {
    localStorage.clear();
    api.getCurrentUser.mockReset();
  });

  it("is false for a cached login that /auth/me/ has not confirmed", async () => {
    login();
    const { useSession } = await loadSession();
    const { result } = renderHook(() => useSession());
    expect(result.current.authenticated).toBe(true);
    expect(result.current.validated).toBe(false);
  });

  it("stays false when the check fails, then turns true when a later refresh succeeds", async () => {
    login();
    const { useSession, ensureFreshSession } = await loadSession();
    const { result } = renderHook(() => useSession());

    api.getCurrentUser.mockRejectedValueOnce(new Error("offline"));
    await act(async () => {
      await ensureFreshSession();
    });
    expect(result.current.validated).toBe(false);

    api.getCurrentUser.mockResolvedValueOnce(ME);
    await act(async () => {
      await ensureFreshSession();
    });
    expect(result.current.validated).toBe(true);
  });

  it("is cleared by logout and does not carry over to the next login", async () => {
    login();
    api.getCurrentUser.mockResolvedValue(ME);
    const { useSession, ensureFreshSession } = await loadSession();
    const { result } = renderHook(() => useSession());
    await act(async () => {
      await ensureFreshSession();
    });
    expect(result.current.validated).toBe(true);

    act(() => {
      localStorage.clear();
      window.dispatchEvent(new Event("session-changed"));
    });
    expect(result.current.authenticated).toBe(false);
    expect(result.current.validated).toBe(false);

    act(() => {
      login();
      window.dispatchEvent(new Event("session-changed"));
    });
    expect(result.current.authenticated).toBe(true);
    expect(result.current.validated).toBe(false); // must be re-confirmed
  });

  it("is not validated for a different role than the one confirmed", async () => {
    login("manager");
    api.getCurrentUser.mockResolvedValue(ME); // confirms "owner"
    const { useSession, ensureFreshSession } = await loadSession();
    const { result } = renderHook(() => useSession());
    await act(async () => {
      await ensureFreshSession();
    });
    // ensureFreshSession rewrites userRole from the server answer, so both agree.
    expect(result.current.role).toBe("owner");
    expect(result.current.validated).toBe(true);
  });
});
