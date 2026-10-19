import { NextRequest, NextResponse } from "next/server";
import {
  ACCESS_COOKIE,
  REFRESH_COOKIE,
  apiOrigin,
  clearSessionCookies,
  downstreamHeaders,
  hasForeignOrigin,
  isTokenIssuingPath,
  refreshAccess,
  setAccessCookie,
  upstreamHeaders,
} from "@/lib/server/bff";

// BFF proxy (docs/frontend-plan.md §3.1): every /api/v1/* call from the browser lands here,
// gets the bearer token from the httpOnly cookie, and is forwarded to Django. An expired
// access token is refreshed server-side and the request replayed once.

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
  // Buffered once so the request can be replayed after a token refresh (multipart uploads included).
  const body = hasBody ? await request.arrayBuffer() : undefined;

  const send = (access: string | null) =>
    fetch(target, {
      method: request.method,
      headers: upstreamHeaders(request, access),
      body,
      redirect: "manual",
      cache: "no-store",
    });

  const accessCookie = request.cookies.get(ACCESS_COOKIE)?.value ?? null;
  const refreshCookie = request.cookies.get(REFRESH_COOKIE)?.value ?? null;

  let upstream: Response;
  let renewedAccess: string | null = null;
  try {
    upstream = await send(accessCookie);
    if ((!accessCookie || upstream.status === 401) && refreshCookie) {
      const refreshed = await refreshAccess(refreshCookie, request);
      if (!refreshed.ok) {
        // Only a definitive rejection (expired/revoked/suspended) ends the session; a backend
        // blip must not log the user out.
        if (refreshed.status === 401 || refreshed.status === 403) {
          const res = NextResponse.json(refreshed.body ?? {}, {
            status: 401,
            headers: { "cache-control": "no-store" },
          });
          clearSessionCookies(res);
          return res;
        }
        return json(502, { detail: "Could not reach the server." });
      }
      renewedAccess = refreshed.access;
      upstream = await send(renewedAccess);
    }
  } catch {
    return json(502, { detail: "Could not reach the server." });
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
