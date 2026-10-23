// @vitest-environment node
// src/proxy.ts: CSP on every document response (marketing pages included), the signed-out
// redirect, and the "no Set-Cookie for anonymous marketing visitors" rule (docs/deployment.md, WP11).
import { afterEach, describe, expect, test } from "vitest";
import { NextRequest } from "next/server";
import { config, isMarketingPath, proxy } from "../proxy";
import { buildCsp, cspMode } from "@/lib/csp";

const ORIGIN = "https://www.pglive.in";
const REPORT_URI = "https://o1.ingest.sentry.io/api/2/security/?sentry_key=k";

function run(path: string, cookies = "") {
  return proxy(new NextRequest(`${ORIGIN}${path}`, { headers: cookies ? { cookie: cookies } : {} }));
}

function setEnv(mode: string | undefined) {
  if (mode === undefined) delete process.env.CSP_MODE;
  else process.env.CSP_MODE = mode;
  process.env.CSP_REPORT_URI = REPORT_URI;
}

afterEach(() => {
  delete process.env.CSP_MODE;
  delete process.env.CSP_REPORT_URI;
});

describe.each([
  ["report-only", "content-security-policy-report-only", "content-security-policy"],
  ["enforce", "content-security-policy", "content-security-policy-report-only"],
])("CSP_MODE=%s", (mode, header, otherHeader) => {
  test.each(["/", "/features", "/pricing", "/login", "/dashboard", "/does-not-exist"])(
    "%s carries the policy under the right header",
    (path) => {
      setEnv(mode);
      const res = run(path, "pg_session=1");
      const policy = res.headers.get(header);
      expect(policy).toContain("default-src 'self'");
      expect(policy).toMatch(/script-src 'self' 'nonce-[A-Za-z0-9+/=]+' 'strict-dynamic'/);
      expect(policy).toContain("report-uri " + REPORT_URI);
      expect(res.headers.get(otherHeader)).toBeNull();
      expect(res.headers.get("reporting-endpoints")).toBe(`csp="${REPORT_URI}"`);
    }
  );

  test("the signed-out redirect carries the policy too", () => {
    setEnv(mode);
    const res = run("/dashboard");
    expect(res.status).toBe(307);
    expect(res.headers.get("location")).toBe(`${ORIGIN}/login`);
    expect(res.headers.get(header)).toContain("default-src 'self'");
  });

  test("the nonce is fresh per request and handed to Next via the request header", () => {
    setEnv(mode);
    const nonce = (res: Response) => /'nonce-([^']+)'/.exec(res.headers.get(header) ?? "")?.[1];
    const a = run("/");
    const b = run("/");
    expect(nonce(a)).toBeTruthy();
    expect(nonce(a)).not.toBe(nonce(b));
    // NextResponse.next({ request: { headers } }) exposes overridden request headers like this.
    expect(a.headers.get(`x-middleware-request-${header}`)).toContain(`'nonce-${nonce(a)}'`);
  });
});

describe("cookies and redirects (unchanged behaviour)", () => {
  test.each(["/", "/features", "/pricing/", "/app", "/contact", "/privacy", "/terms", "/refund-policy", "/delete-account"])(
    "anonymous marketing page %s gets no Set-Cookie and no redirect",
    (path) => {
      setEnv("report-only");
      const res = run(path);
      expect(res.headers.get("set-cookie")).toBeNull();
      expect(res.headers.get("location")).toBeNull();
    }
  );

  test("app pages still get the default locale cookie", () => {
    const res = run("/login");
    expect(res.headers.get("set-cookie")).toContain("NEXT_LOCALE=");
  });

  test.each(["/signup", "/verify-email", "/forgot-password", "/reset-password"])(
    "signed-out %s is reachable (no redirect to /login)",
    (path) => {
      const res = run(path);
      expect(res.headers.get("location")).toBeNull();
    }
  );

  test("other signed-out app pages still redirect to /login", () => {
    expect(run("/signup/extra").headers.get("location")).toBe(`${ORIGIN}/login`);
  });

  test("signed-in app pages pass through", () => {
    const res = run("/residents", "pg_session=1; NEXT_LOCALE=te");
    expect(res.headers.get("location")).toBeNull();
    expect(res.headers.get("set-cookie")).toBeNull();
  });

  test("marketing detection is exact", () => {
    expect(isMarketingPath("/")).toBe(true);
    expect(isMarketingPath("/features/pricing-table")).toBe(true);
    expect(isMarketingPath("/apps")).toBe(false);
    expect(isMarketingPath("/dashboard")).toBe(false);
  });
});

describe("CSP mode defaults", () => {
  test("off in development, report-only in production unless configured", () => {
    expect(cspMode({ NODE_ENV: "development" })).toBe("off");
    expect(cspMode({ NODE_ENV: "production" })).toBe("report-only");
    expect(cspMode({ NODE_ENV: "production", CSP_MODE: "enforce" })).toBe("enforce");
    expect(cspMode({ NODE_ENV: "production", CSP_MODE: "bogus" })).toBe("report-only");
  });

  test("dev requests get no CSP header", () => {
    setEnv("off");
    const res = run("/");
    expect(res.headers.get("content-security-policy")).toBeNull();
    expect(res.headers.get("content-security-policy-report-only")).toBeNull();
  });

  test("without a report URI there is no reporting directive", () => {
    expect(buildCsp("n")).not.toContain("report-uri");
  });
});

describe("matcher", () => {
  const matcher = new RegExp(`^${config.matcher[0]}$`);
  test.each(["/", "/features", "/login", "/dashboard", "/residents/42"])("runs for %s", (path) => {
    expect(matcher.test(path)).toBe(true);
  });
  test.each([
    "/api/v1/residents/",
    "/_next/static/chunks/a.js",
    "/_next/image",
    "/sw.js",
    "/manifest.webmanifest",
    "/icons/icon-192.png",
    "/favicon.ico",
    "/robots.txt",
    "/brand/pglive-logo.png",
  ])("skips %s", (path) => {
    expect(matcher.test(path)).toBe(false);
  });
});
