// Server-only helpers for the BFF proxy (docs/frontend-plan.md §3.1): the browser
// never sees a JWT. Route handlers under app/api hold the token pair in httpOnly
// cookies, call Django server-side, and refresh the access token transparently.
// Imported by route handlers only — never from a client component.

import type { NextRequest, NextResponse } from "next/server";
import { originHeaders } from "./originSignature";

export const ACCESS_COOKIE = "pg_access";
export const REFRESH_COOKIE = "pg_refresh";
/** Presence marker for `proxy.ts` (page navigations never carry the /api-scoped token cookies). Holds no secret. */
export const SESSION_COOKIE = "pg_session";

const FALLBACK_ACCESS_MAX_AGE_S = 14 * 60; // backend SIMPLE_JWT ACCESS_TOKEN_LIFETIME is 15 min
const FALLBACK_REFRESH_MAX_AGE_S = 7 * 24 * 60 * 60;

/** Server-side Django origin. `localhost` inside the frontend container is not Django, hence INTERNAL_API_URL. */
export function apiOrigin(): string {
  return (
    process.env.INTERNAL_API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
  ).replace(/\/+$/, "");
}

/** Endpoints that return a token pair. Only the dedicated handlers may call them, so a
 * generic proxied call can never hand tokens to page JavaScript. */
const TOKEN_ISSUING_PATHS = new Set([
  "auth/login",
  "auth/login-phone",
  "auth/token/refresh",
  "auth/otp/verify",
  "auth/otp/email/verify",
]);

export function isTokenIssuingPath(apiPath: string): boolean {
  return TOKEN_ISSUING_PATHS.has(apiPath.replace(/^v1\//, "").replace(/\/+$/, ""));
}

const DEFAULT_MAX_BODY_BYTES = 10 * 1024 * 1024;

/** Largest request body the proxy will buffer. The backend has no upload limit of its own beyond
 * Django's defaults, so this is the real ceiling: sized for a phone photo, overridable per
 * deployment. Keep the edge's `client_max_body_size` at or above it. */
export function maxBodyBytes(): number {
  const configured = Number(process.env.BFF_MAX_BODY_BYTES);
  return Number.isFinite(configured) && configured > 0 ? configured : DEFAULT_MAX_BODY_BYTES;
}

/** Reads the request body, giving up (null) the moment it exceeds `maxBytes`. Checks the declared
 * Content-Length first, then counts bytes as they stream, so a chunked body with no length header
 * cannot grow the Next.js process's memory without bound. */
export async function readBodyLimited(request: NextRequest, maxBytes: number): Promise<ArrayBuffer | null> {
  const declared = Number(request.headers.get("content-length"));
  if (Number.isFinite(declared) && declared > maxBytes) return null;
  if (!request.body) return new ArrayBuffer(0);

  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > maxBytes) {
      await reader.cancel().catch(() => {});
      return null;
    }
    chunks.push(value);
  }
  const body = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return body.buffer as ArrayBuffer;
}

const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

/** CSRF defence in depth on top of SameSite=Lax: a state-changing request must come from this app's own origin. */
export function hasForeignOrigin(request: NextRequest): boolean {
  if (!UNSAFE_METHODS.has(request.method)) return false;
  const origin = request.headers.get("origin");
  if (!origin) return false; // same-origin fetches may omit it; Lax cookies already block cross-site posts
  const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  try {
    return new URL(origin).host !== host;
  } catch {
    return true;
  }
}

/** Headers forwarded to Django. Everything else (cookies above all) stays behind. */
const FORWARDED_REQUEST_HEADERS = ["content-type", "accept", "accept-language", "idempotency-key", "user-agent"];

/** Set by the load balancer on every request to this app, overwriting any client value. */
const CLIENT_IP_HEADER = "x-pglive-client-ip";

/** The upstream request being prepared: the browser IP signature covers its method and URL. */
export type UpstreamTarget = { method: string; url: string };

export function upstreamHeaders(request: NextRequest, accessToken: string | null, target: UpstreamTarget): Headers {
  const headers = new Headers();
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  // Audit logs (invariant 9) and login throttling need the browser's IP. X-Forwarded-For is
  // client-controlled behind Google's load balancer, so it is never forwarded; the IP the load
  // balancer wrote goes upstream signed instead (docs/deployment.md, WP7).
  const origin = originHeaders(request.headers.get(CLIENT_IP_HEADER), target.method, target.url);
  for (const [name, value] of Object.entries(origin)) headers.set(name, value);
  if (accessToken) headers.set("authorization", `Bearer ${accessToken}`);
  return headers;
}

const STRIPPED_RESPONSE_HEADERS = new Set([
  "content-encoding", // fetch() already decoded the body
  "content-length",
  "transfer-encoding",
  "connection",
  "keep-alive",
  "set-cookie", // Django never sets browser cookies through the BFF
]);

export function downstreamHeaders(upstream: Headers): Headers {
  const headers = new Headers();
  upstream.forEach((value, name) => {
    if (!STRIPPED_RESPONSE_HEADERS.has(name.toLowerCase())) headers.set(name, value);
  });
  headers.set("cache-control", "no-store");
  return headers;
}

/** Seconds until a JWT's `exp`, so the cookie expires with the token it carries. */
function secondsUntilExpiry(jwt: string, fallback: number): number {
  try {
    const payload = JSON.parse(Buffer.from(jwt.split(".")[1], "base64url").toString("utf8"));
    const remaining = Number(payload.exp) - Math.floor(Date.now() / 1000);
    return Number.isFinite(remaining) && remaining > 0 ? remaining : fallback;
  } catch {
    return fallback;
  }
}

const secure = () => process.env.NODE_ENV === "production";

export function setAccessCookie(response: NextResponse, access: string) {
  response.cookies.set(ACCESS_COOKIE, access, {
    httpOnly: true,
    secure: secure(),
    sameSite: "lax",
    path: "/api",
    maxAge: secondsUntilExpiry(access, FALLBACK_ACCESS_MAX_AGE_S),
  });
}

export function setSessionCookies(response: NextResponse, tokens: { access: string; refresh: string }) {
  setAccessCookie(response, tokens.access);
  const refreshMaxAge = secondsUntilExpiry(tokens.refresh, FALLBACK_REFRESH_MAX_AGE_S);
  response.cookies.set(REFRESH_COOKIE, tokens.refresh, {
    httpOnly: true,
    secure: secure(),
    sameSite: "lax",
    path: "/api",
    maxAge: refreshMaxAge,
  });
  response.cookies.set(SESSION_COOKIE, "1", {
    httpOnly: true,
    secure: secure(),
    sameSite: "lax",
    path: "/",
    maxAge: refreshMaxAge,
  });
}

export function clearSessionCookies(response: NextResponse) {
  for (const [name, path] of [
    [ACCESS_COOKIE, "/api"],
    [REFRESH_COOKIE, "/api"],
    [SESSION_COOKIE, "/"],
  ] as const) {
    response.cookies.set(name, "", { httpOnly: true, secure: secure(), sameSite: "lax", path, maxAge: 0 });
  }
}

export type RefreshResult =
  | { ok: true; access: string }
  | { ok: false; status: number; body: unknown };

/** Exchanges the refresh cookie for a new access token. Never throws; an unreachable backend is a 502. */
export async function refreshAccess(refresh: string, request: NextRequest): Promise<RefreshResult> {
  try {
    const url = `${apiOrigin()}/api/v1/auth/token/refresh/`;
    const headers = upstreamHeaders(request, null, { method: "POST", url });
    headers.set("content-type", "application/json");
    const res = await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify({ refresh }),
      cache: "no-store",
    });
    const body = await res.json().catch(() => ({}));
    if (res.ok && typeof body.access === "string") return { ok: true, access: body.access };
    return { ok: false, status: res.status, body };
  } catch {
    return { ok: false, status: 502, body: { detail: "Could not reach the server." } };
  }
}
