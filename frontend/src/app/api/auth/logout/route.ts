import { NextResponse } from "next/server";
import { clearSessionCookies } from "@/lib/server/bff";

export const dynamic = "force-dynamic";

// Django has no token blacklist, so logout is cookie removal; the refresh token simply
// stops being presented by this browser.
export function POST() {
  const response = new NextResponse(null, { status: 204, headers: { "cache-control": "no-store" } });
  clearSessionCookies(response);
  return response;
}
