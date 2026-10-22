// Server-only. Calls Django as the signed-in user from a dedicated route handler (one that must
// act on the response itself, e.g. to install a new token pair), mirroring the generic proxy's
// refresh rules (app/api/[...path]/route.ts): an expired access cookie is refreshed BEFORE the
// call so it runs once, and a request is only replayed after Django answered 401 (it did not run).

import type { NextRequest } from "next/server";
import { ACCESS_COOKIE, REFRESH_COOKIE, refreshAccess, upstreamHeaders } from "./bff";

export type AuthenticatedCall =
  /** Django answered. `renewedAccess` is set when the access token had to be refreshed first. */
  | { kind: "response"; upstream: Response; renewedAccess: string | null }
  /** No valid session: no cookies, or the refresh token was definitively rejected. */
  | { kind: "session-ended"; body: unknown }
  /** Django could not be reached. The session is untouched: an outage must not log anyone out. */
  | { kind: "unreachable" };

const isDefinitive = (status: number) => status === 401 || status === 403;

export async function callAsUser(
  request: NextRequest,
  target: string,
  init: { method: string; body: ArrayBuffer }
): Promise<AuthenticatedCall> {
  let access = request.cookies.get(ACCESS_COOKIE)?.value ?? null;
  const refreshCookie = request.cookies.get(REFRESH_COOKIE)?.value ?? null;
  let renewedAccess: string | null = null;

  const send = (token: string) => {
    const headers = upstreamHeaders(request, token, { method: init.method, url: target });
    headers.set("content-type", "application/json");
    return fetch(target, { method: init.method, headers, body: init.body, cache: "no-store" });
  };

  try {
    if (!access) {
      if (!refreshCookie) return { kind: "session-ended", body: {} };
      const refreshed = await refreshAccess(refreshCookie, request);
      if (!refreshed.ok) {
        return isDefinitive(refreshed.status)
          ? { kind: "session-ended", body: refreshed.body ?? {} }
          : { kind: "unreachable" };
      }
      access = renewedAccess = refreshed.access;
    }

    let upstream = await send(access);

    if (upstream.status === 401 && !renewedAccess && refreshCookie) {
      const refreshed = await refreshAccess(refreshCookie, request);
      if (!refreshed.ok) {
        return isDefinitive(refreshed.status)
          ? { kind: "session-ended", body: refreshed.body ?? {} }
          : { kind: "unreachable" };
      }
      renewedAccess = refreshed.access;
      upstream = await send(renewedAccess);
    }

    if (upstream.status === 401) {
      return { kind: "session-ended", body: await upstream.json().catch(() => ({})) };
    }
    return { kind: "response", upstream, renewedAccess };
  } catch {
    return { kind: "unreachable" };
  }
}
