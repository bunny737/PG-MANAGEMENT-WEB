// Signed browser IP for Django (docs/deployment.md, WP7). Server-only.
//
// The load balancer in front of Django sees this BFF, not the browser, so the BFF forwards the
// browser's address (which the load balancer in front of *this* app wrote into
// `x-pglive-client-ip`, overwriting anything the client sent) with an HMAC over a canonical
// string. backend/apps/core/net.py verifies it and must stay byte-for-byte identical; both sides
// assert backend/apps/core/tests_fixtures/origin_signature_vectors.json.

import { createHmac } from "node:crypto";
import { isIP } from "node:net";

const SIGNATURE_VERSION = "v1";

/** Canonical text form, or null: IPv4 dotted quad, IPv6 RFC 5952 (compressed, lowercase),
 * IPv4-mapped IPv6 collapsed to IPv4 — the same rules as Python's ipaddress in net.py. */
export function normalizeIp(value: string | null | undefined): string | null {
  const raw = (value ?? "").trim();
  const kind = isIP(raw);
  if (kind === 4) return raw;
  if (kind !== 6) return null;
  let host: string;
  try {
    // The WHATWG URL serializer compresses the longest zero run and lower-cases (RFC 5952).
    host = new URL(`http://[${raw}]/`).hostname.slice(1, -1);
  } catch {
    return null;
  }
  const mapped = /^::ffff:([0-9a-f]{1,4}):([0-9a-f]{1,4})$/.exec(host);
  if (mapped) {
    const high = parseInt(mapped[1], 16);
    const low = parseInt(mapped[2], 16);
    return [high >> 8, high & 0xff, low >> 8, low & 0xff].join(".");
  }
  return host;
}

/** `path` and `query` are raw (still percent-encoded) exactly as sent upstream; `query` has no
 * leading "?" and is not re-sorted. */
export function canonicalString(ip: string, ts: string, method: string, path: string, query: string): string {
  return `${SIGNATURE_VERSION}\n${ip}\n${ts}\n${method.toUpperCase()}\n${path}\n${query}`;
}

export function signOrigin(secret: string, ip: string, ts: string, method: string, path: string, query: string) {
  return createHmac("sha256", secret).update(canonicalString(ip, ts, method, path, query), "utf8").digest("hex");
}

/** Headers carrying the signed browser IP for one upstream request, or none when there is nothing
 * trustworthy to sign (no secret configured — dev — or no load-balancer client header). The
 * signature covers the URL exactly as fetch() will put it on the wire. */
export function originHeaders(
  clientIpHeader: string | null,
  method: string,
  upstreamUrl: string,
  secret = process.env.BFF_ORIGIN_SECRET ?? "",
  now = Date.now()
): Record<string, string> {
  const ip = normalizeIp(clientIpHeader);
  if (!secret || !ip) return {};
  const url = new URL(upstreamUrl);
  const ts = String(Math.floor(now / 1000));
  return {
    "x-pglive-origin-ip": ip,
    "x-pglive-origin-ts": ts,
    "x-pglive-origin-sig": signOrigin(secret, ip, ts, method, url.pathname, url.search.replace(/^\?/, "")),
  };
}
