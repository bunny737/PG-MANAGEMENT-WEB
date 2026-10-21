// Content-Security-Policy for every HTML response (docs/deployment.md, WP11). Built per request in
// src/proxy.ts with a fresh nonce: Next applies the nonce from the request's CSP header to its own
// inline scripts, and 'strict-dynamic' lets those nonce'd scripts load Razorpay Checkout and the
// Google Maps loader (both injected at runtime, see lib/razorpay.ts and PropertyMapPicker.tsx).
//
// CSP_MODE (runtime env, read per request — switching needs no rebuild):
//   report-only  Content-Security-Policy-Report-Only (default in production)
//   enforce      Content-Security-Policy
//   off          no header (default in development, where Next's dev runtime needs eval)
// Rollback after enforcing = set CSP_MODE=report-only and deploy a new revision.

export type CspMode = "off" | "report-only" | "enforce";

export function cspMode(env: Record<string, string | undefined> = process.env): CspMode {
  const configured = (env.CSP_MODE ?? "").trim().toLowerCase();
  if (configured === "off" || configured === "report-only" || configured === "enforce") return configured;
  return env.NODE_ENV === "production" ? "report-only" : "off";
}

export function cspHeaderName(mode: Exclude<CspMode, "off">) {
  return mode === "enforce" ? "Content-Security-Policy" : "Content-Security-Policy-Report-Only";
}

export function buildCsp(nonce: string, reportUri?: string): string {
  const directives: Record<string, string[]> = {
    "default-src": ["'self'"],
    "script-src": [
      "'self'",
      `'nonce-${nonce}'`,
      "'strict-dynamic'",
      // Fallbacks for browsers without 'strict-dynamic' (CSP2); ignored by CSP3 browsers.
      "https://checkout.razorpay.com",
      "https://maps.googleapis.com",
    ],
    // Tailwind/Next and the Maps widget inject inline styles.
    "style-src": ["'self'", "'unsafe-inline'", "https://fonts.googleapis.com"],
    "img-src": [
      "'self'",
      "data:",
      "blob:",
      "https://storage.googleapis.com", // signed GCS URLs (property images, documents)
      "https://*.googleapis.com",
      "https://*.gstatic.com",
      "https://*.razorpay.com",
    ],
    "font-src": ["'self'", "data:", "https://fonts.gstatic.com"],
    "connect-src": [
      "'self'",
      "https://*.googleapis.com", // Maps, FCM registration, Firebase installations
      "https://*.razorpay.com",
    ],
    "frame-src": ["https://api.razorpay.com", "https://checkout.razorpay.com"],
    "worker-src": ["'self'", "blob:"],
    "manifest-src": ["'self'"],
    "object-src": ["'none'"],
    "base-uri": ["'self'"],
    "form-action": ["'self'", "https://api.razorpay.com"],
    "frame-ancestors": ["'self'"],
  };
  if (reportUri) {
    directives["report-uri"] = [reportUri];
    directives["report-to"] = ["csp"];
  }
  return Object.entries(directives)
    .map(([name, values]) => `${name} ${values.join(" ")}`)
    .join("; ");
}

/** Headers to add to a response: the policy plus, when reporting, the Reporting API endpoint. */
export function cspResponseHeaders(
  nonce: string,
  env: Record<string, string | undefined> = process.env
): Record<string, string> {
  const mode = cspMode(env);
  if (mode === "off") return {};
  const reportUri = env.CSP_REPORT_URI?.trim() || undefined;
  const headers: Record<string, string> = { [cspHeaderName(mode)]: buildCsp(nonce, reportUri) };
  if (reportUri) headers["Reporting-Endpoints"] = `csp="${reportUri}"`;
  return headers;
}

export function newNonce(): string {
  return btoa(crypto.randomUUID());
}
