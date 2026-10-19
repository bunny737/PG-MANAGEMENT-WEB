// @vitest-environment node
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { NextRequest } from "next/server";
import { GET, POST } from "../[...path]/route";
import { POST as loginPost } from "../auth/login/route";
import { POST as logoutPost } from "../auth/logout/route";

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

  test("attaches the bearer token from the cookie and forwards path, slash, query and client IP", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { results: [] }));
    const res = await GET(
      request("/api/v1/residents/?status=active", {
        headers: {
          cookie: "pg_access=tok-1; pg_refresh=ref-1; other=secret",
          "x-forwarded-for": "203.0.113.9",
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
    expect(sent.get("x-forwarded-for")).toBe("203.0.113.9");
    expect(sent.get("accept-language")).toBe("te");
    expect(sent.get("cookie")).toBeNull(); // cookies never reach Django
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

  test.each(["v1/auth/login/", "v1/auth/login-phone/", "v1/auth/token/refresh/", "v1/auth/otp/verify/"])(
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
    const access = jwt(900);
    const refresh = jwt(7 * 86400);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { access, refresh }))
      .mockResolvedValueOnce(jsonResponse(200, { id: "u1", role: "owner", permissions: [] }));

    const res = await loginPost(
      request("/api/auth/login", {
        method: "POST",
        headers: { "content-type": "application/json", "x-forwarded-for": "203.0.113.9" },
        body: JSON.stringify({ email: "o@example.com", password: "pw" }),
      })
    );

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
    // Login throttling and audit need the client IP, not the Next server's.
    expect((fetchMock.mock.calls[0][1].headers as Headers).get("x-forwarded-for")).toBe("203.0.113.9");
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

  test("logout clears all three session cookies", async () => {
    const res = await logoutPost();
    expect(res.status).toBe(204);
    const set = res.headers.get("set-cookie") ?? "";
    for (const name of ["pg_access", "pg_refresh", "pg_session"]) expect(set).toContain(`${name}=;`);
  });
});
