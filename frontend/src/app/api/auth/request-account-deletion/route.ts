// Request account deletion. Django ends every session when a deletion is requested (the
// account is locked) and answers with a fresh token pair so the caller can still see and cancel
// the request; this handler stores it in the httpOnly cookies (the browser never sees a JWT) and
// returns only the request itself. It cannot go through the generic proxy, which refuses POSTs to
// this path for exactly that reason. Viewing and cancelling (GET/DELETE) carry no tokens and use
// the generic proxy.

import { NextRequest, NextResponse } from "next/server";
import {
  apiOrigin,
  clearSessionCookies,
  hasForeignOrigin,
  readBodyLimited,
  setAccessCookie,
  setSessionCookies,
} from "@/lib/server/bff";
import { callAsUser } from "@/lib/server/authenticatedUpstream";

export const dynamic = "force-dynamic";

const NO_STORE = { "cache-control": "no-store" };
const MAX_BODY_BYTES = 16 * 1024;

function json(status: number, body: unknown) {
  return NextResponse.json(body, { status, headers: NO_STORE });
}

export async function POST(request: NextRequest) {
  if (hasForeignOrigin(request)) return json(403, { detail: "Cross-origin request blocked." });

  const body = await readBodyLimited(request, MAX_BODY_BYTES);
  if (body === null) return json(413, { detail: "Request body too large." });

  const call = await callAsUser(request, `${apiOrigin()}/api/v1/auth/account/deletion/`, {
    method: "POST",
    body,
  });

  if (call.kind === "unreachable") return json(502, { detail: "Could not reach the server." });
  if (call.kind === "session-ended") {
    const response = json(401, call.body);
    clearSessionCookies(response);
    return response;
  }

  const { upstream, renewedAccess } = call;
  if (!upstream.ok) {
    // Wrong password or code, throttling, a request that already exists: nothing was requested, so
    // the session stays as it was (plus the renewed access token, if it was refreshed on the way).
    const response = json(upstream.status, await upstream.json().catch(() => ({})));
    if (renewedAccess) setAccessCookie(response, renewedAccess);
    return response;
  }

  const created = await upstream.json().catch(() => ({}));
  if (typeof created.access !== "string" || typeof created.refresh !== "string") {
    // The request exists but no usable session came back, and the old tokens are dead: end the
    // session. Signing in again lands on the pending screen, where it can be reviewed or cancelled.
    const response = json(502, { detail: "Deletion requested, but the session could not be renewed." });
    clearSessionCookies(response);
    return response;
  }

  // Token-free body: no follow-up call that could fail and strand the new session.
  const response = json(201, { deletion: created.deletion ?? null });
  setSessionCookies(response, { access: created.access, refresh: created.refresh });
  return response;
}
