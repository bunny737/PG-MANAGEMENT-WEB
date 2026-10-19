import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { clearSession } from "../api";
import { disablePush, enablePush, getPushStatus, setFirebaseLoader } from "../push";
import { pushTargetUrl } from "../pushLinks";

// The real SDK needs a service worker and FCM, so push.ts exposes a loader seam for tests.
const getToken = vi.fn(async (): Promise<string> => "token-1");
const deleteToken = vi.fn(async (): Promise<boolean> => true);
setFirebaseLoader((async () => [
  { initializeApp: () => ({}), getApps: () => [] },
  { getMessaging: () => ({}), getToken, deleteToken, onMessage: vi.fn() },
]) as unknown as Parameters<typeof setFirebaseLoader>[0]);

const ANDROID_CHROME =
  "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36";
const IPHONE_SAFARI =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1";
const STORAGE_KEY = "pushSubscription";

function stubBrowser({
  userAgent = ANDROID_CHROME,
  standalone = false,
  permission = "default" as NotificationPermission,
  requestPermission = vi.fn(async () => permission),
} = {}) {
  vi.stubGlobal("navigator", {
    userAgent,
    platform: userAgent === IPHONE_SAFARI ? "iPhone" : "Linux",
    maxTouchPoints: 5,
    standalone,
    serviceWorker: { ready: Promise.resolve({}) },
  });
  vi.stubGlobal("matchMedia", () => ({ matches: standalone }));
  window.matchMedia = (() => ({ matches: standalone })) as unknown as typeof window.matchMedia;
  vi.stubGlobal("PushManager", class {});
  vi.stubGlobal("Notification", { permission, requestPermission });
  return requestPermission;
}

function stubFirebaseEnv() {
  vi.stubEnv("NODE_ENV", "production");
  vi.stubEnv("NEXT_PUBLIC_FIREBASE_API_KEY", "key");
  vi.stubEnv("NEXT_PUBLIC_FIREBASE_PROJECT_ID", "proj");
  vi.stubEnv("NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID", "sender");
  vi.stubEnv("NEXT_PUBLIC_FIREBASE_APP_ID", "app");
  vi.stubEnv("NEXT_PUBLIC_FIREBASE_VAPID_KEY", "vapid");
}

beforeEach(() => {
  localStorage.clear();
  stubFirebaseEnv();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.clearAllMocks();
});

describe("getPushStatus", () => {
  test("iPhone in a Safari tab must install first: the push APIs only exist for an installed app", () => {
    stubBrowser({ userAgent: IPHONE_SAFARI, standalone: false });
    expect(getPushStatus()).toBe("needs-install");
  });

  test("installed iPhone app can turn notifications on", () => {
    stubBrowser({ userAgent: IPHONE_SAFARI, standalone: true });
    expect(getPushStatus()).toBe("off");
  });

  test("a denied permission is reported as blocked, not offered again", () => {
    stubBrowser({ permission: "denied" });
    expect(getPushStatus()).toBe("blocked");
  });

  test("on only when permission is granted AND this device has a registered subscription", () => {
    stubBrowser({ permission: "granted" });
    expect(getPushStatus()).toBe("off");
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ id: "sub-1", token: "token-1" }));
    expect(getPushStatus()).toBe("on");
  });

  test("unsupported without Firebase config or outside a production build (no service worker in dev)", () => {
    stubBrowser();
    vi.stubEnv("NEXT_PUBLIC_FIREBASE_VAPID_KEY", "");
    expect(getPushStatus()).toBe("unsupported");

    stubFirebaseEnv();
    vi.stubEnv("NODE_ENV", "development");
    expect(getPushStatus()).toBe("unsupported");
  });
});

describe("enablePush / disablePush", () => {
  function stubApi(responses: Record<string, () => Response> = {}) {
    const calls: { url: string; method: string; body?: string }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
        const url = String(input);
        calls.push({ url, method: init?.method ?? "GET", body: init?.body as string | undefined });
        const match = Object.entries(responses).find(([prefix]) => url.includes(prefix));
        return match ? match[1]() : new Response(null, { status: 204 });
      })
    );
    return calls;
  }
  const json = (status: number, body: unknown) => () =>
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

  test("asks for permission first, then registers the token as a web device", async () => {
    const order: string[] = [];
    const requestPermission = vi.fn(async () => {
      order.push("permission");
      return "granted" as NotificationPermission;
    });
    stubBrowser({ requestPermission });
    getToken.mockImplementationOnce(async () => {
      order.push("token");
      return "token-1";
    });
    const calls = stubApi({ "push-subscriptions": json(201, { id: "sub-1" }) });

    await enablePush();

    expect(order).toEqual(["permission", "token"]); // permission is the first await, so iOS keeps the tap
    const post = calls.find((c) => c.method === "POST");
    expect(post?.url).toBe("/api/v1/notifications/push-subscriptions/");
    expect(JSON.parse(post?.body ?? "{}")).toEqual({ fcm_token: "token-1", device_type: "web" });
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null")).toEqual({ id: "sub-1", token: "token-1" });
  });

  test("a rotated token replaces the previous registration instead of leaving a duplicate", async () => {
    stubBrowser({ permission: "granted" });
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ id: "old-sub", token: "old-token" }));
    const calls = stubApi({ "push-subscriptions": json(201, { id: "new-sub" }) });

    await enablePush();

    expect(JSON.parse(calls.find((c) => c.method === "POST")?.body ?? "{}").replaces).toBe("old-sub");
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null").id).toBe("new-sub");
  });

  test("a declined permission never reaches the network", async () => {
    stubBrowser({ permission: "denied" });
    const calls = stubApi();
    await expect(enablePush()).resolves.toBe("blocked");
    expect(calls).toHaveLength(0);
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  test("disable removes the server row, revokes the token at FCM and clears local state", async () => {
    stubBrowser({ permission: "granted" });
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ id: "sub-1", token: "token-1" }));
    const calls = stubApi();

    await disablePush();

    expect(calls).toEqual([
      expect.objectContaining({ url: "/api/v1/notifications/push-subscriptions/sub-1/", method: "DELETE" }),
    ]);
    expect(deleteToken).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  test("disable still revokes the token when the server call fails (offline logout)", async () => {
    stubBrowser({ permission: "granted" });
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ id: "sub-1", token: "token-1" }));
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("offline"))));

    await expect(disablePush()).resolves.toBeUndefined();

    expect(deleteToken).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  test("the FCM token is revoked BEFORE the server call, so a slow request can't outlive the session", async () => {
    stubBrowser({ permission: "granted" });
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ id: "sub-1", token: "token-1" }));
    const order: string[] = [];
    deleteToken.mockImplementationOnce(async () => {
      order.push("revoke-token");
      return true;
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        order.push("server-delete");
        return new Response(null, { status: 204 });
      })
    );
    await disablePush();
    expect(order).toEqual(["revoke-token", "server-delete"]);
  });

  describe("revocation racing the next account's registration", () => {
    const OLD_ROW = { id: "sub-1", token: "token-1" };

    function stallRevocation() {
      let release: () => void = () => {};
      const gate = new Promise<void>((resolve) => {
        release = resolve;
      });
      deleteToken.mockImplementationOnce(async () => {
        await gate;
        return true;
      });
      return release;
    }

    function stubApiCreates() {
      const calls: string[] = [];
      vi.stubGlobal(
        "fetch",
        vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
          calls.push(`${init?.method ?? "GET"} ${String(input)}`);
          return new Response(JSON.stringify({ id: "new-sub" }), { status: 201, headers: { "Content-Type": "application/json" } });
        })
      );
      return calls;
    }

    test("a registration waits for a revocation that has already started, and never lands before it finishes", async () => {
      stubBrowser({ permission: "granted" });
      localStorage.setItem(STORAGE_KEY, JSON.stringify(OLD_ROW));
      const release = stallRevocation();
      stubApiCreates();

      const cleanup = disablePush();
      await vi.waitFor(() => expect(deleteToken).toHaveBeenCalledTimes(1)); // revocation is now stalled mid-flight

      const registration = enablePush(); // the next account registers while it is still running
      await new Promise((resolve) => setTimeout(resolve, 30));
      expect(getToken).not.toHaveBeenCalled(); // serialized behind the revocation, so it cannot be hit by it

      release();
      await Promise.all([cleanup, registration]);

      expect(getToken).toHaveBeenCalledTimes(1);
      expect(deleteToken).toHaveBeenCalledTimes(1);
      expect(JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null")?.id).toBe("new-sub");
    });

    test("a revocation abandoned by the timeout that then finishes late re-registers the newer token", async () => {
      vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
      try {
        stubBrowser({ permission: "granted" });
        localStorage.setItem(STORAGE_KEY, JSON.stringify(OLD_ROW));
        const release = stallRevocation();
        const calls = stubApiCreates();

        const cleanup = disablePush();
        await vi.advanceTimersByTimeAsync(0);
        expect(deleteToken).toHaveBeenCalledTimes(1); // stalled

        const registration = enablePush();
        await vi.advanceTimersByTimeAsync(10_000); // the cap gives up on the stalled revocation
        await cleanup; // disablePush itself is released too, WITHOUT the revocation having resolved
        await registration; // the new account registered while the revocation was still hanging
        expect(getToken).toHaveBeenCalledTimes(1);

        release(); // ...and now the abandoned revocation finishes, possibly having hit that new token
        await vi.advanceTimersByTimeAsync(0);

        expect(getToken).toHaveBeenCalledTimes(2); // repaired: registered again
        expect(calls.filter((c) => c.startsWith("POST") && c.includes("push-subscriptions"))).toHaveLength(2);
        expect(JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null")?.id).toBe("new-sub");
      } finally {
        vi.useRealTimers();
      }
    });

    test("a revocation that never resolves still lets disablePush reach the server-side delete", async () => {
      vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
      try {
        stubBrowser({ permission: "granted" });
        localStorage.setItem(STORAGE_KEY, JSON.stringify(OLD_ROW));
        deleteToken.mockImplementationOnce(() => new Promise<boolean>(() => {})); // hangs forever
        const calls = stubApiCreates();

        let settled = false;
        const cleanup = disablePush().then(() => {
          settled = true;
        });
        await vi.advanceTimersByTimeAsync(9_999);
        expect(settled).toBe(false); // still inside the cap
        expect(calls.some((c) => c.startsWith("DELETE"))).toBe(false);

        await vi.advanceTimersByTimeAsync(1); // the cap expires
        await cleanup;

        expect(settled).toBe(true);
        expect(calls).toContain("DELETE /api/v1/notifications/push-subscriptions/sub-1/"); // the previous user's backend row is removed
        expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
      } finally {
        vi.useRealTimers();
      }
    });

    test("a registration that hangs rejects after the cap instead of leaving the UI waiting", async () => {
      vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
      try {
        stubBrowser({ permission: "granted" });
        getToken.mockImplementationOnce(() => new Promise<string>(() => {}));
        stubApiCreates();
        const outcome = enablePush().then(
          () => "resolved",
          () => "rejected"
        );
        await vi.advanceTimersByTimeAsync(10_000);
        await expect(outcome).resolves.toBe("rejected");
      } finally {
        vi.useRealTimers();
      }
    });

    describe("a timed-out registration that completes after the session changed", () => {
      const ACCOUNT_A = { id: "user-a", tenant_id: "tenant-1" };
      const ACCOUNT_B = { id: "user-b", tenant_id: "tenant-1" };

      async function timeOutRegistrationOfA() {
        vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
        stubBrowser({ permission: "granted" });
        localStorage.setItem("currentUser", JSON.stringify(ACCOUNT_A));
        let release: () => void = () => {};
        const gate = new Promise<void>((resolve) => {
          release = resolve;
        });
        getToken.mockImplementationOnce(async () => {
          await gate;
          return "token-a";
        });
        const calls = stubApiCreates();

        const outcome = enablePush().then(
          () => "resolved",
          () => "rejected"
        );
        await vi.advanceTimersByTimeAsync(10_000);
        await expect(outcome).resolves.toBe("rejected"); // the caller has been released...
        return { release, calls }; // ...but Firebase is still working on A's token
      }

      test("after logout: no POST and no storage write once Firebase finally answers", async () => {
        try {
          const { release, calls } = await timeOutRegistrationOfA();

          await disablePush(); // A logs out (the pre-logout step)
          localStorage.setItem("currentUser", JSON.stringify(ACCOUNT_B)); // B logs in

          release(); // Firebase resolves under B's session
          await vi.advanceTimersByTimeAsync(0);

          expect(calls.filter((c) => c.includes("push-subscriptions"))).toEqual([]);
          expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
        } finally {
          vi.useRealTimers();
        }
      });

      test("account replaced without a cleanup running: the identity check still stops it", async () => {
        try {
          const { release, calls } = await timeOutRegistrationOfA();

          localStorage.setItem("currentUser", JSON.stringify(ACCOUNT_B)); // no disablePush at all

          release();
          await vi.advanceTimersByTimeAsync(0);

          expect(calls.filter((c) => c.includes("push-subscriptions"))).toEqual([]);
          expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
        } finally {
          vi.useRealTimers();
        }
      });

      test("turning notifications off while a registration is pending cancels it", async () => {
        try {
          const { release, calls } = await timeOutRegistrationOfA();
          await disablePush();
          release();
          await vi.advanceTimersByTimeAsync(0);
          expect(calls.filter((c) => c.includes("push-subscriptions"))).toEqual([]);
          expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
        } finally {
          vi.useRealTimers();
        }
      });

      test("the same session still completes normally", async () => {
        stubBrowser({ permission: "granted" });
        localStorage.setItem("currentUser", JSON.stringify(ACCOUNT_A));
        const calls = stubApiCreates();
        await enablePush();
        expect(calls.filter((c) => c.startsWith("POST") && c.includes("push-subscriptions"))).toHaveLength(1);
        expect(JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null")?.id).toBe("new-sub");
      });
    });

    test("a revocation that finishes in time does not trigger a pointless re-registration", async () => {
      stubBrowser({ permission: "granted" });
      localStorage.setItem(STORAGE_KEY, JSON.stringify(OLD_ROW));
      stubApiCreates();
      await disablePush();
      expect(getToken).not.toHaveBeenCalled();
    });
  });

  test("a device that never subscribed does nothing on disable", async () => {
    stubBrowser({ permission: "granted" });
    const calls = stubApi();
    await disablePush();
    expect(calls).toHaveLength(0);
    expect(deleteToken).not.toHaveBeenCalled();
  });

  test("logout unsubscribes BEFORE the session cookie is cleared", async () => {
    stubBrowser({ permission: "granted" });
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ id: "sub-1", token: "token-1" }));
    const calls = stubApi();

    await clearSession();

    const order = calls.map((c) => `${c.method} ${c.url}`);
    const unsubscribe = order.indexOf("DELETE /api/v1/notifications/push-subscriptions/sub-1/");
    const logout = order.indexOf("POST /api/auth/logout");
    expect(unsubscribe).toBeGreaterThanOrEqual(0);
    expect(logout).toBeGreaterThan(unsubscribe);
  });
});

describe("pushTargetUrl", () => {
  const id = "3f2a9c1e-5b7d-4e8f-9a10-2b3c4d5e6f70";

  test("routes each notification type to its screen", () => {
    expect(pushTargetUrl(`invoice:${id}`)).toBe(`/billing/invoices/${id}`);
    expect(pushTargetUrl(`payment:${id}`)).toBe(`/billing/payments/${id}`);
    expect(pushTargetUrl(`tenant_trial:${id}:55`)).toBe("/settings");
  });

  test("anything unrecognised or malformed lands on the dashboard, never an arbitrary path", () => {
    for (const reference of ["", null, undefined, "invoice:not-a-uuid", "invoice:../../admin", "other:1", `invoice:${id}/../x`]) {
      expect(pushTargetUrl(reference)).toBe("/dashboard");
    }
  });
});
