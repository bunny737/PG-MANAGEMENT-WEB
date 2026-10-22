// @vitest-environment node
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { NextRequest } from "next/server";
import { GET, POST } from "../[...path]/route";
import { POST as changePasswordPost } from "../auth/change-password/route";
import { POST as loginPost } from "../auth/login/route";
import { POST as loginEmailOtpPost } from "../auth/login-email-otp/route";
import { POST as logoutPost } from "../auth/logout/route";
import { signOrigin } from "@/lib/server/originSignature";

const ORIGIN = "http://app.test";

// A JWT-shaped string whose payload carries `exp`, so cookie lifetimes follow the token.
function jwt(expInSeconds: number) {
  const payload = Buffer.from(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + expInSeconds })).toString(
    "base64url"
  );
  return `h.${payload}.s`;
}

function request(path: string, init: { method?: string; headers?: Record<string, string>; body?: string } = {}) {
  return new NextRequest(`${ORIGIN}${path}`, {
    method: init.method ?? "GET",
    headers: init.headers,
    body: init.body,
  });
}

const params = (path: string) => ({ params: Promise.resolve({ path: path.split("/") }) });

function jsonResponse(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

describe("BFF proxy", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    process.env.INTERNAL_API_URL = "http://django.test";
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("attaches the bearer token from the cookie and forwards path, slash, query and a signed client IP", async () => {
    process.env.BFF_ORIGIN_SECRET = "test-secret";
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { results: [] }));
    const res = await GET(
      request("/api/v1/residents/?status=active", {
        headers: {
          cookie: "pg_access=tok-1; pg_refresh=ref-1; other=secret",
          "x-pglive-client-ip": "203.0.113.9", // written by the load balancer
          "x-forwarded-for": "198.51.100.66", // client-controlled: never forwarded
          "accept-language": "te",
        },
      }),
      params("v1/residents/")
    );

    expect(res.status).toBe(200);
    expect(res.headers.get("cache-control")).toBe("no-store");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://django.test/api/v1/residents/?status=active");
    const sent = init.headers as Headers;
    expect(sent.get("authorization")).toBe("Bearer tok-1");
    expect(sent.get("x-forwarded-for")).toBeNull();
    expect(sent.get("x-pglive-origin-ip")).toBe("203.0.113.9");
    const ts = sent.get("x-pglive-origin-ts")!;
    expect(sent.get("x-pglive-origin-sig")).toBe(
      signOrigin("test-secret", "203.0.113.9", ts, "GET", "/api/v1/residents/", "status=active")
    );
    expect(sent.get("accept-language")).toBe("te");
    expect(sent.get("cookie")).toBeNull(); // cookies never reach Django
    delete process.env.BFF_ORIGIN_SECRET;
  });

  test("sends the edge key from the environment on every upstream call, and never one a browser supplies", async () => {
    process.env.BFF_EDGE_KEY = "edge-key-0123456789abcdef0123456789abcdef";
    fetchMock.mockResolvedValue(jsonResponse(200, {}));
    await GET(
      request("/api/v1/residents/", {
        headers: { cookie: "pg_access=tok", "x-pglive-edge-key": "browser-forged-value" },
      }),
      params("v1/residents/")
    );
    expect((fetchMock.mock.calls[0][1].headers as Headers).get("x-pglive-edge-key")).toBe(
      "edge-key-0123456789abcdef0123456789abcdef"
    );

    delete process.env.BFF_EDGE_KEY;
    fetchMock.mockClear();
    await GET(
      request("/api/v1/residents/", {
        headers: { cookie: "pg_access=tok", "x-pglive-edge-key": "browser-forged-value" },
      }),
      params("v1/residents/")
    );
    expect((fetchMock.mock.calls[0][1].headers as Headers).get("x-pglive-edge-key")).toBeNull();
  });

  test("sends no origin signature without a secret or a load-balancer client IP", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, {}));
    await GET(request("/api/v1/residents/", { headers: { "x-pglive-client-ip": "203.0.113.9" } }), params("v1/residents/"));
    process.env.BFF_ORIGIN_SECRET = "test-secret";
    await GET(request("/api/v1/residents/", { headers: { "x-forwarded-for": "203.0.113.9" } }), params("v1/residents/"));
    delete process.env.BFF_ORIGIN_SECRET;
    for (const [, init] of fetchMock.mock.calls) {
      const sent = init.headers as Headers;
      expect(sent.get("x-pglive-origin-sig")).toBeNull();
      expect(sent.get("x-forwarded-for")).toBeNull();
    }
  });

  test("refreshes an expired access token server-side and replays the request body once", async () => {
    const renewed = jwt(900);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(401, { detail: "expired" }))
      .mockResolvedValueOnce(jsonResponse(200, { access: renewed }))
      .mockResolvedValueOnce(jsonResponse(201, { id: "pay-1" }));

    const res = await POST(
      request("/api/v1/payments/", {
        method: "POST",
        headers: { cookie: "pg_access=old; pg_refresh=ref-1", "content-type": "application/json", "idempotency-key": "k1" },
        body: JSON.stringify({ amount: "100.00" }),
      }),
      params("v1/payments/")
    );

    expect(res.status).toBe(201);
    expect(fetchMock.mock.calls[1][0]).toBe("http://django.test/api/v1/auth/token/refresh/");
    const replay = fetchMock.mock.calls[2][1];
    expect((replay.headers as Headers).get("authorization")).toBe(`Bearer ${renewed}`);
    expect((replay.headers as Headers).get("idempotency-key")).toBe("k1");
    expect(Buffer.from(replay.body as ArrayBuffer).toString()).toBe('{"amount":"100.00"}');
    const set = res.headers.get("set-cookie") ?? "";
    expect(set).toContain(`pg_access=${renewed}`);
    expect(set).toMatch(/HttpOnly/i);
  });

  test("an expired access cookie is refreshed BEFORE the request, which then runs exactly once", async () => {
    const renewed = jwt(900);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { access: renewed })) // refresh
      .mockResolvedValueOnce(jsonResponse(201, { id: "x" })); // the request itself
    const res = await POST(
      request("/api/v1/residents/", {
        method: "POST",
        headers: { cookie: "pg_refresh=ref-1", "content-type": "application/json" },
        body: "{}",
      }),
      params("v1/residents/")
    );
    expect(res.status).toBe(201);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[0][0]).toBe("http://django.test/api/v1/auth/token/refresh/");
    expect((fetchMock.mock.calls[1][1].headers as Headers).get("authorization")).toBe(`Bearer ${renewed}`);
    expect(res.headers.get("set-cookie") ?? "").toContain(`pg_access=${renewed}`);
  });

  test("a successful public write is never replayed when only a stale refresh cookie is present", async () => {
    // Signup / OTP request / password reset are anonymous: running one twice sends two emails.
    fetchMock
      .mockResolvedValueOnce(jsonResponse(401, { code: "token_not_valid" })) // refresh rejected
      .mockResolvedValueOnce(jsonResponse(201, { detail: "sent" })); // the public endpoint
    const res = await POST(
      request("/api/v1/auth/password-reset/", {
        method: "POST",
        headers: { cookie: "pg_refresh=dead", "content-type": "application/json" },
        body: '{"email":"a@b.co"}',
      }),
      params("v1/auth/password-reset/")
    );
    expect(res.status).toBe(201);
    const upstreamCalls = fetchMock.mock.calls.filter(([url]) => String(url).includes("password-reset"));
    expect(upstreamCalls).toHaveLength(1);
    expect((upstreamCalls[0][1].headers as Headers).get("authorization")).toBeNull();
    const set = res.headers.get("set-cookie") ?? "";
    for (const name of ["pg_access", "pg_refresh", "pg_session"]) expect(set).toContain(`${name}=;`);
  });

  test("a non-401 answer is never followed by a refresh or a replay", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(400, { detail: "validation" }));
    const res = await POST(
      request("/api/v1/residents/", {
        method: "POST",
        headers: { cookie: "pg_access=tok; pg_refresh=ref-1", "content-type": "application/json" },
        body: "{}",
      }),
      params("v1/residents/")
    );
    expect(res.status).toBe(400);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  describe("request body limit", () => {
    beforeEach(() => {
      process.env.BFF_MAX_BODY_BYTES = "10";
    });
    afterEach(() => {
      delete process.env.BFF_MAX_BODY_BYTES;
    });

    test("a declared Content-Length over the limit is rejected before anything is forwarded", async () => {
      const res = await POST(
        request("/api/v1/properties/", { method: "POST", headers: { "content-length": "11" }, body: "x".repeat(11) }),
        params("v1/properties/")
      );
      expect(res.status).toBe(413);
      expect(fetchMock).not.toHaveBeenCalled();
    });

    test("a chunked body with no Content-Length is cut off once it passes the limit", async () => {
      let pulled = 0;
      const stream = new ReadableStream<Uint8Array>({
        pull(controller) {
          pulled += 1;
          controller.enqueue(new Uint8Array(4)); // endless 4-byte chunks
        },
      });
      const req = new NextRequest(`${ORIGIN}/api/v1/properties/`, {
        method: "POST",
        body: stream,
        duplex: "half", // required by Node for a streamed request body
      } as ConstructorParameters<typeof NextRequest>[1]);
      const res = await POST(req, params("v1/properties/"));
      expect(res.status).toBe(413);
      expect(pulled).toBeLessThan(10); // stopped reading rather than draining the stream
      expect(fetchMock).not.toHaveBeenCalled();
    });

    test("a body at the limit still goes through", async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse(201, { id: "p" }));
      const res = await POST(
        request("/api/v1/properties/", { method: "POST", body: "x".repeat(10) }),
        params("v1/properties/")
      );
      expect(res.status).toBe(201);
    });

    test("login bodies are capped too", async () => {
      const res = await loginPost(
        request("/api/auth/login", { method: "POST", headers: { "content-length": String(1024 * 1024) }, body: "{}" })
      );
      expect(res.status).toBe(413);
      expect(fetchMock).not.toHaveBeenCalled();
    });
  });

  test("a rejected refresh ends the session: 401 and every session cookie cleared", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(401, {}))
      .mockResolvedValueOnce(jsonResponse(401, { code: "subscription_suspended" }));
    const res = await GET(
      request("/api/v1/residents/", { headers: { cookie: "pg_access=old; pg_refresh=ref-1" } }),
      params("v1/residents/")
    );
    expect(res.status).toBe(401);
    expect((await res.json()).code).toBe("subscription_suspended");
    const set = res.headers.get("set-cookie") ?? "";
    for (const name of ["pg_access", "pg_refresh", "pg_session"]) expect(set).toContain(`${name}=;`);
  });

  test("an unreachable backend during refresh is a 502 and does NOT log the user out", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(401, {})).mockRejectedValueOnce(new Error("ECONNREFUSED"));
    const res = await GET(
      request("/api/v1/residents/", { headers: { cookie: "pg_access=old; pg_refresh=ref-1" } }),
      params("v1/residents/")
    );
    expect(res.status).toBe(502);
    expect(res.headers.get("set-cookie") ?? "").not.toContain("pg_refresh");
  });

  test("anonymous calls are forwarded without Authorization and never trigger a refresh", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { plans: [] }));
    await GET(request("/api/v1/subscriptions/plans/"), params("v1/subscriptions/plans/"));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect((fetchMock.mock.calls[0][1].headers as Headers).get("authorization")).toBeNull();
  });

  test.each([
    "v1/auth/login/",
    "v1/auth/login-phone/",
    "v1/auth/token/refresh/",
    "v1/auth/otp/verify/",
    "v1/auth/otp/email/verify/",
    "v1/auth/password/change/",
  ])(
    "token-issuing endpoint %s is not reachable through the generic proxy",
    async (path) => {
      const res = await POST(request(`/api/${path}`, { method: "POST", body: "{}" }), params(path));
      expect(res.status).toBe(404);
      expect(fetchMock).not.toHaveBeenCalled();
    }
  );

  test("a state-changing request from a foreign origin is rejected", async () => {
    const res = await POST(
      request("/api/v1/payments/", { method: "POST", headers: { origin: "https://evil.test", host: "app.test" }, body: "{}" }),
      params("v1/payments/")
    );
    expect(res.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("auth route handlers", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    process.env.INTERNAL_API_URL = "http://django.test";
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("login stores the token pair in httpOnly cookies and returns only the profile", async () => {
    process.env.BFF_ORIGIN_SECRET = "test-secret";
    const access = jwt(900);
    const refresh = jwt(7 * 86400);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { access, refresh }))
      .mockResolvedValueOnce(jsonResponse(200, { id: "u1", role: "owner", permissions: [] }));

    const res = await loginPost(
      request("/api/auth/login", {
        method: "POST",
        headers: { "content-type": "application/json", "x-pglive-client-ip": "203.0.113.9" },
        body: JSON.stringify({ email: "o@example.com", password: "pw" }),
      })
    );
    delete process.env.BFF_ORIGIN_SECRET;

    expect(res.status).toBe(200);
    const text = await res.text();
    expect(text).not.toContain(access);
    expect(text).not.toContain(refresh);
    expect(JSON.parse(text).role).toBe("owner");
    const set = res.headers.get("set-cookie") ?? "";
    expect(set).toContain(`pg_access=${access}`);
    expect(set).toContain(`pg_refresh=${refresh}`);
    expect(set).toContain("pg_session=1");
    expect((set.match(/HttpOnly/gi) ?? []).length).toBe(3);
    // Login throttling and audit need the client IP, not the Next server's — signed, for both calls.
    for (const [url, init] of fetchMock.mock.calls.slice(0, 2)) {
      const sent = init.headers as Headers;
      const { pathname } = new URL(url as string);
      expect(sent.get("x-pglive-origin-ip")).toBe("203.0.113.9");
      expect(sent.get("x-pglive-origin-sig")).toBe(
        signOrigin("test-secret", "203.0.113.9", sent.get("x-pglive-origin-ts")!, init.method ?? "GET", pathname, "")
      );
    }
  });

  test("bad credentials pass Django's status and body through and set no cookies", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(401, { detail: "No active account found." }));
    const res = await loginPost(
      request("/api/auth/login", { method: "POST", headers: { "content-type": "application/json" }, body: "{}" })
    );
    expect(res.status).toBe(401);
    expect((await res.json()).detail).toBe("No active account found.");
    expect(res.headers.get("set-cookie")).toBeNull();
  });

  test("email-code login verifies against Django and keeps the tokens in httpOnly cookies", async () => {
    const access = jwt(900);
    const refresh = jwt(7 * 86400);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { access, refresh }))
      .mockResolvedValueOnce(jsonResponse(200, { id: "u1", role: "manager", permissions: [] }));

    const res = await loginEmailOtpPost(
      request("/api/auth/login-email-otp", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email: "m@example.com", code: "123456" }),
      })
    );

    expect(new URL(fetchMock.mock.calls[0][0] as string).pathname).toBe("/api/v1/auth/otp/email/verify/");
    expect(res.status).toBe(200);
    const text = await res.text();
    expect(text).not.toContain(access);
    expect(text).not.toContain(refresh);
    expect(JSON.parse(text)).not.toHaveProperty("access");
    expect(JSON.parse(text)).not.toHaveProperty("refresh");
    const set = res.headers.get("set-cookie") ?? "";
    expect(set).toContain(`pg_access=${access}`);
    expect(set).toContain(`pg_refresh=${refresh}`);
    expect((set.match(/HttpOnly/gi) ?? []).length).toBe(3);
  });

  test("a wrong email code passes Django's 401 through and sets no cookies", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(401, { code: "INVALID_OTP", detail: "The code is incorrect or has expired." })
    );
    const res = await loginEmailOtpPost(
      request("/api/auth/login-email-otp", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email: "m@example.com", code: "000000" }),
      })
    );
    expect(res.status).toBe(401);
    expect((await res.json()).code).toBe("INVALID_OTP");
    expect(res.headers.get("set-cookie")).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1); // no /auth/me/ without tokens
  });

  test("email-code login from a foreign origin is rejected before reaching Django", async () => {
    const res = await loginEmailOtpPost(
      request("/api/auth/login-email-otp", {
        method: "POST",
        headers: { origin: "https://evil.test", host: "app.test" },
        body: "{}",
      })
    );
    expect(res.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test("logout clears all three session cookies", async () => {
    const res = await logoutPost();
    expect(res.status).toBe(204);
    const set = res.headers.get("set-cookie") ?? "";
    for (const name of ["pg_access", "pg_refresh", "pg_session"]) expect(set).toContain(`${name}=;`);
  });
});

describe("change-password route handler", () => {
  let fetchMock: ReturnType<typeof vi.fn>;
  const CHANGE_URL = "http://django.test/api/v1/auth/password/change/";
  const BODY = JSON.stringify({ current_password: "old-pw", new_password: "new-pw-123" });

  function change(cookie: string, init: { headers?: Record<string, string>; body?: string } = {}) {
    return changePasswordPost(
      request("/api/auth/change-password", {
        method: "POST",
        headers: { cookie, "content-type": "application/json", ...init.headers },
        body: init.body ?? BODY,
      })
    );
  }

  const setCookie = (res: Response) => res.headers.get("set-cookie") ?? "";
  const cleared = (res: Response) => {
    for (const name of ["pg_access", "pg_refresh", "pg_session"]) expect(setCookie(res)).toContain(`${name}=;`);
  };

  beforeEach(() => {
    process.env.INTERNAL_API_URL = "http://django.test";
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("calls Django as the signed-in user, installs the new token pair, and returns no token", async () => {
    const access = jwt(900);
    const refresh = jwt(7 * 86400);
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { access, refresh }));

    const res = await change("pg_access=old-access; pg_refresh=old-refresh");

    expect(fetchMock).toHaveBeenCalledTimes(1); // no follow-up /auth/me/ that could strand the session
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(CHANGE_URL);
    expect((init.headers as Headers).get("authorization")).toBe("Bearer old-access");
    expect(Buffer.from(init.body as ArrayBuffer).toString()).toBe(BODY);
    expect(res.status).toBe(200);
    const text = await res.text();
    expect(JSON.parse(text)).toEqual({ ok: true });
    expect(text).not.toContain(access);
    expect(text).not.toContain(refresh);
    expect(setCookie(res)).toContain(`pg_access=${access}`);
    expect(setCookie(res)).toContain(`pg_refresh=${refresh}`);
    expect(setCookie(res)).toContain("pg_session=1");
    expect((setCookie(res).match(/HttpOnly/gi) ?? []).length).toBe(3);
  });

  test("a 400 (wrong or weak password) passes Django's body through and leaves the session alone", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(400, { current_password: ["Current password is incorrect."] }));
    const res = await change("pg_access=tok; pg_refresh=ref");
    expect(res.status).toBe(400);
    expect((await res.json()).current_password[0]).toBe("Current password is incorrect.");
    expect(res.headers.get("set-cookie")).toBeNull();
  });

  test("an expired access cookie is refreshed first, so the change runs exactly once", async () => {
    const renewed = jwt(900);
    const access = jwt(901);
    const refresh = jwt(7 * 86400);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { access: renewed })) // refresh
      .mockResolvedValueOnce(jsonResponse(200, { access, refresh })); // the change
    const res = await change("pg_refresh=old-refresh");

    expect(fetchMock.mock.calls[0][0]).toBe("http://django.test/api/v1/auth/token/refresh/");
    expect(fetchMock.mock.calls[1][0]).toBe(CHANGE_URL);
    expect((fetchMock.mock.calls[1][1].headers as Headers).get("authorization")).toBe(`Bearer ${renewed}`);
    expect(res.status).toBe(200);
    // The installed pair is the one Django returned, not the interim renewed token.
    expect(setCookie(res)).toContain(`pg_access=${access}`);
    expect(setCookie(res)).not.toContain(`pg_access=${renewed}`);
  });

  test("a rejected access token is refreshed and the change replayed once", async () => {
    const renewed = jwt(900);
    const access = jwt(902);
    const refresh = jwt(7 * 86400);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(401, { detail: "expired" })) // 401: the change did not run
      .mockResolvedValueOnce(jsonResponse(200, { access: renewed })) // refresh
      .mockResolvedValueOnce(jsonResponse(200, { access, refresh })); // replay
    const res = await change("pg_access=stale; pg_refresh=old-refresh");

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect((fetchMock.mock.calls[2][1].headers as Headers).get("authorization")).toBe(`Bearer ${renewed}`);
    expect(res.status).toBe(200);
    expect(setCookie(res)).toContain(`pg_refresh=${refresh}`);
  });

  test("a validation error after a refresh keeps the renewed access token but not a new session", async () => {
    const renewed = jwt(900);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { access: renewed }))
      .mockResolvedValueOnce(jsonResponse(400, { new_password: ["too weak"] }));
    const res = await change("pg_refresh=old-refresh");
    expect(res.status).toBe(400);
    expect(setCookie(res)).toContain(`pg_access=${renewed}`);
    expect(setCookie(res)).not.toContain("pg_refresh=");
    expect(setCookie(res)).not.toContain("pg_session=");
  });

  test("a rejected refresh ends the session: 401 and every session cookie cleared", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(401, {}))
      .mockResolvedValueOnce(jsonResponse(401, { code: "password_changed" }));
    const res = await change("pg_access=stale; pg_refresh=old-refresh");
    expect(res.status).toBe(401);
    expect((await res.json()).code).toBe("password_changed");
    cleared(res);
  });

  test("with no session cookies it answers 401 and never calls Django", async () => {
    const res = await change("other=1");
    expect(res.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
    cleared(res);
  });

  test("an unreachable backend is a 502 and does NOT log the user out", async () => {
    fetchMock.mockRejectedValueOnce(new Error("ECONNREFUSED"));
    const res = await change("pg_access=tok; pg_refresh=ref");
    expect(res.status).toBe(502);
    expect(res.headers.get("set-cookie")).toBeNull();
  });

  test("a success without a usable token pair ends the session instead of keeping dead tokens", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, {}));
    const res = await change("pg_access=tok; pg_refresh=ref");
    expect(res.status).toBe(502);
    cleared(res);
  });

  test("a foreign origin is rejected before reaching Django", async () => {
    const res = await change("pg_access=tok", { headers: { origin: "https://evil.test", host: "app.test" } });
    expect(res.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test("an oversized body is rejected", async () => {
    const res = await change("pg_access=tok", { headers: { "content-length": String(1024 * 1024) } });
    expect(res.status).toBe(413);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
