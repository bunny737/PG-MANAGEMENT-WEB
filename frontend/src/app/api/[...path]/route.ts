import { NextRequest, NextResponse } from "next/server";
import {
  ACCESS_COOKIE,
  REFRESH_COOKIE,
  apiOrigin,
  clearSessionCookies,
  downstreamHeaders,
  hasForeignOrigin,
  isTokenIssuingPath,
  maxBodyBytes,
  readBodyLimited,
  refreshAccess,
  setAccessCookie,
  upstreamHeaders,
} from "@/lib/server/bff";

// BFF proxy (docs/frontend-plan.md §3.1): every /api/v1/* call from the browser lands here,
// gets the bearer token from the httpOnly cookie, and is forwarded to Django. An expired
// access token is refreshed server-side first, and a request is only ever replayed after the
// backend answered 401 (which means it did not run).

export const dynamic = "force-dynamic";

const NULL_BODY_STATUSES = new Set([101, 204, 205, 304]);

function json(status: number, body: unknown) {
  return NextResponse.json(body, { status, headers: { "cache-control": "no-store" } });
}

async function handle(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  if (isTokenIssuingPath(path.join("/"))) {
    return json(404, { detail: "Not found." });
  }
  if (hasForeignOrigin(request)) {
    return json(403, { detail: "Cross-origin request blocked." });
  }

  // Keep Django's trailing slash: Next would otherwise normalise it away (see skipTrailingSlashRedirect).
  const target = `${apiOrigin()}${new URL(request.url).pathname}${request.nextUrl.search}`;
  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  // Buffered once so the request can be replayed after a token refresh (multipart uploads
  // included), but never beyond the limit: this runs before authentication.
  const body = hasBody ? await readBodyLimited(request, maxBodyBytes()) : undefined;
  if (body === null) {
    return json(413, { detail: "Request body too large." });
  }

  const send = (access: string | null) =>
    fetch(target, {
      method: request.method,
      headers: upstreamHeaders(request, access, { method: request.method, url: target }),
      body,
      redirect: "manual",
      cache: "no-store",
    });

  let access = request.cookies.get(ACCESS_COOKIE)?.value ?? null;
  const refreshCookie = request.cookies.get(REFRESH_COOKIE)?.value ?? null;

  let renewedAccess: string | null = null;
  /** Set when the refresh token was definitively rejected (expired, revoked, suspended). */
  let sessionEnded: unknown = null;
  let upstream: Response;

  // A definitive rejection ends the session; an unreachable backend must not log the user out.
  const isDefinitive = (status: number) => status === 401 || status === 403;

  try {
    if (!access && refreshCookie) {
      // The access cookie has expired and the browser no longer sends it. Refresh BEFORE the
      // request, so it runs exactly once: sending it anonymously first and replaying it after
      // would execute a public write (signup, OTP request, password reset) twice.
      const refreshed = await refreshAccess(refreshCookie, request);
      if (refreshed.ok) {
        access = renewedAccess = refreshed.access;
      } else if (isDefinitive(refreshed.status)) {
        sessionEnded = refreshed.body ?? {};
      } else {
        return json(502, { detail: "Could not reach the server." });
      }
    }

    upstream = await send(access);

    if (upstream.status === 401 && access && !renewedAccess && refreshCookie) {
      // The access token was present but rejected: the request did not run, so replaying is safe.
      const refreshed = await refreshAccess(refreshCookie, request);
      if (refreshed.ok) {
        renewedAccess = refreshed.access;
        upstream = await send(renewedAccess);
      } else if (isDefinitive(refreshed.status)) {
        sessionEnded = refreshed.body ?? {};
      } else {
        return json(502, { detail: "Could not reach the server." });
      }
    }
  } catch {
    return json(502, { detail: "Could not reach the server." });
  }

  if (sessionEnded !== null) {
    // A public endpoint that succeeded stays a success; one that needed the session reports why
    // it ended (e.g. subscription_suspended). Either way the dead cookies are cleared.
    const response =
      upstream.status === 401
        ? json(401, sessionEnded)
        : new NextResponse(NULL_BODY_STATUSES.has(upstream.status) ? null : upstream.body, {
            status: upstream.status,
            headers: downstreamHeaders(upstream.headers),
          });
    clearSessionCookies(response);
    return response;
  }

  const response = new NextResponse(NULL_BODY_STATUSES.has(upstream.status) ? null : upstream.body, {
    status: upstream.status,
    headers: downstreamHeaders(upstream.headers),
  });
  if (renewedAccess) setAccessCookie(response, renewedAccess);
  return response;
}

export {
  handle as GET,
  handle as POST,
  handle as PUT,
  handle as PATCH,
  handle as DELETE,
  handle as HEAD,
};
