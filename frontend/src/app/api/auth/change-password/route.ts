// Change password. Django ends every session when a password changes and answers with a fresh
// token pair; this handler stores it in the httpOnly cookies (the browser never sees a JWT) so the
// caller stays signed in. It cannot go through the generic proxy, which refuses token-issuing paths.

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

  const call = await callAsUser(request, `${apiOrigin()}/api/v1/auth/password/change/`, {
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
    // Wrong current password, weak new password, throttling: the password did not change, so the
    // session stays as it was (plus the renewed access token, if it was refreshed on the way).
    const response = json(upstream.status, await upstream.json().catch(() => ({})));
    if (renewedAccess) setAccessCookie(response, renewedAccess);
    return response;
  }

  const tokens = await upstream.json().catch(() => ({}));
  if (typeof tokens.access !== "string" || typeof tokens.refresh !== "string") {
    // The password changed but no usable session came back. The old tokens are dead, so end the
    // session and let the user sign in with the new password.
    const response = json(502, { detail: "Password changed, but the session could not be renewed." });
    clearSessionCookies(response);
    return response;
  }

  // Token-free body: no follow-up call that could fail and strand the new session.
  const response = json(200, { ok: true });
  setSessionCookies(response, { access: tokens.access, refresh: tokens.refresh });
  return response;
}
