// Shared body of the two login route handlers (email/password and staff phone/password).
// Django returns the token pair; this stores it in httpOnly cookies and hands the browser
// only the /auth/me/ payload, so no JWT ever reaches page JavaScript.

import { NextRequest, NextResponse } from "next/server";
import {
  apiOrigin,
  clearSessionCookies,
  hasForeignOrigin,
  readBodyLimited,
  setSessionCookies,
  upstreamHeaders,
} from "@/lib/server/bff";

const NO_STORE = { "cache-control": "no-store" };

/** A login body is a couple of short fields. */
const LOGIN_MAX_BODY_BYTES = 16 * 1024;

export async function handleLogin(request: NextRequest, upstreamPath: string) {
  if (hasForeignOrigin(request)) {
    return NextResponse.json({ detail: "Cross-origin request blocked." }, { status: 403, headers: NO_STORE });
  }

  const body = await readBodyLimited(request, LOGIN_MAX_BODY_BYTES);
  if (body === null) {
    return NextResponse.json({ detail: "Request body too large." }, { status: 413, headers: NO_STORE });
  }

  try {
    const headers = upstreamHeaders(request, null);
    headers.set("content-type", "application/json");
    const login = await fetch(`${apiOrigin()}${upstreamPath}`, {
      method: "POST",
      headers,
      body,
      cache: "no-store",
    });
    const tokens = await login.json().catch(() => ({}));
    // Bad credentials, throttling, suspended tenant: pass Django's status and error body through.
    if (!login.ok || typeof tokens.access !== "string" || typeof tokens.refresh !== "string") {
      return NextResponse.json(tokens, { status: login.ok ? 502 : login.status, headers: NO_STORE });
    }

    const meHeaders = upstreamHeaders(request, tokens.access);
    const me = await fetch(`${apiOrigin()}/api/v1/auth/me/`, { headers: meHeaders, cache: "no-store" });
    const profile = await me.json().catch(() => ({}));
    if (!me.ok) {
      return NextResponse.json(profile, { status: me.status, headers: NO_STORE });
    }

    const response = NextResponse.json(profile, { headers: NO_STORE });
    setSessionCookies(response, { access: tokens.access, refresh: tokens.refresh });
    return response;
  } catch {
    const response = NextResponse.json(
      { detail: "Could not reach the server." },
      { status: 502, headers: NO_STORE }
    );
    clearSessionCookies(response);
    return response;
  }
}
