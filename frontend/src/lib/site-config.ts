import { parseSiteEnv } from "./site-config.validation";

// Read at request time on the server (plain env names, not NEXT_PUBLIC_*), so a
// container can be reconfigured without a rebuild. Only server components use it.
export function getSiteConfig() {
  return parseSiteEnv(process.env).config;
}

/** GA4 measurement ID (e.g. G-XXXXXXXXXX) for the marketing pages, or null when unset/malformed.
 * Strictly validated because it is interpolated into an inline script. */
export function getGaMeasurementId(env: Record<string, string | undefined> = process.env): string | null {
  const id = (env.GA_MEASUREMENT_ID ?? "").trim();
  return /^G-[A-Z0-9]{4,20}$/.test(id) ? id : null;
}

/** Base URL for SERVER-side calls to Django. Inside a container `localhost` is
 * the frontend itself, so production sets INTERNAL_API_URL (e.g. http://backend:8000);
 * the browser never calls Django directly: it uses the same-origin BFF proxy (src/app/api), which
 * reads the same INTERNAL_API_URL. */
export function getServerApiBase(): string {
  return (
    process.env.INTERNAL_API_URL ??
    process.env.NEXT_PUBLIC_API_URL ??
    "http://localhost:8000"
  ).replace(/\/+$/, "");
}
