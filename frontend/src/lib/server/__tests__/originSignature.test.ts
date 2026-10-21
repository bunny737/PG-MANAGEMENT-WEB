// @vitest-environment node
// The backend verifies what this module signs (backend/apps/core/net.py). Both sides assert the
// same vectors file, so the canonical string can never silently drift between Next and Django.
// In Docker the backend fixture is mounted read-only (docker-compose.yml, frontend service).
import fs from "fs";
import path from "path";
import { describe, expect, test } from "vitest";
import { canonicalString, normalizeIp, originHeaders, signOrigin } from "../originSignature";

const FIXTURE = path.resolve(
  __dirname,
  "../../../../../backend/apps/core/tests_fixtures/origin_signature_vectors.json"
);

type Vectors = {
  secret: string;
  signatures: { name: string; ip: string; ts: string; method: string; path: string; query: string; canonical: string; signature: string }[];
  normalize_ip: { input: string; expected: string | null }[];
};
const vectors = JSON.parse(fs.readFileSync(FIXTURE, "utf8")) as Vectors;

describe("origin signature (shared vectors with Django)", () => {
  test.each(vectors.signatures)("$name", (v) => {
    expect(canonicalString(v.ip, v.ts, v.method, v.path, v.query)).toBe(v.canonical);
    expect(signOrigin(vectors.secret, v.ip, v.ts, v.method, v.path, v.query)).toBe(v.signature);
  });

  test.each(vectors.normalize_ip)("normalizeIp($input)", ({ input, expected }) => {
    expect(normalizeIp(input)).toBe(expected);
  });
});

describe("originHeaders", () => {
  const NOW = 1_760_000_000_000;

  test("signs the URL exactly as fetch will send it: encoded path kept, query raw", () => {
    const headers = originHeaders(" 203.0.113.9 ", "get", "https://api.test/api/v1/files/a%2Fb/?q=a%20b+c&x=", "s", NOW);
    expect(headers).toEqual({
      "x-pglive-origin-ip": "203.0.113.9",
      "x-pglive-origin-ts": "1760000000",
      "x-pglive-origin-sig": signOrigin("s", "203.0.113.9", "1760000000", "GET", "/api/v1/files/a%2Fb/", "q=a%20b+c&x="),
    });
  });

  test("non-ASCII path segments are signed in their percent-encoded wire form", () => {
    const headers = originHeaders("203.0.113.9", "GET", "https://api.test/api/v1/tags/తెలుగు/", "s", NOW);
    const encoded = "/api/v1/tags/%E0%B0%A4%E0%B1%86%E0%B0%B2%E0%B1%81%E0%B0%97%E0%B1%81/";
    expect(headers["x-pglive-origin-sig"]).toBe(signOrigin("s", "203.0.113.9", "1760000000", "GET", encoded, ""));
  });

  test("IPv6 and IPv4-mapped addresses are normalised before signing", () => {
    expect(originHeaders("2001:DB8:0:0:0:0:0:1", "GET", "https://api.test/", "s", NOW)["x-pglive-origin-ip"]).toBe("2001:db8::1");
    expect(originHeaders("::ffff:203.0.113.9", "GET", "https://api.test/", "s", NOW)["x-pglive-origin-ip"]).toBe("203.0.113.9");
  });

  test("nothing is signed without a secret or a valid client IP", () => {
    expect(originHeaders("203.0.113.9", "GET", "https://api.test/", "", NOW)).toEqual({});
    expect(originHeaders(null, "GET", "https://api.test/", "s", NOW)).toEqual({});
    expect(originHeaders("not-an-ip", "GET", "https://api.test/", "s", NOW)).toEqual({});
  });
});
