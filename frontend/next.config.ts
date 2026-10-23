import type { NextConfig } from "next";
import { PHASE_PRODUCTION_BUILD } from "next/constants";
import createNextIntlPlugin from "next-intl/plugin";
import withSerwistInit from "@serwist/next";
import { randomUUID } from "node:crypto";
import path from "path";
import { assertLaunchReady } from "./src/lib/site-config.validation";

const withNextIntl = createNextIntlPlugin();

// PWA service worker (docs/frontend-plan.md §5.1). @serwist/next is a webpack plugin, so
// the build runs with `next build --webpack` (see package.json). Registration is manual
// (features/pwa/PwaRegister.tsx) so a waiting update can prompt the user instead of swapping
// code under a half-filled form, and it is off in dev where the worker would cache stale code.
const withSerwist = withSerwistInit({
  swSrc: "src/app/sw.ts",
  swDest: "public/sw.js",
  disable: process.env.NODE_ENV === "development",
  register: false,
  reloadOnOnline: false,
  additionalPrecacheEntries: [{ url: "/~offline", revision: randomUUID() }],
});

// Safe baseline headers for every route. The Content-Security-Policy is NOT here: it needs a
// per-request nonce, so src/proxy.ts sets it on every document response (lib/csp.ts).
// Strict-Transport-Security is not here either: the load balancer adds it to every response
// on all three hosts (docs/deployment.md).
const SECURITY_HEADERS = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-Frame-Options", value: "SAMEORIGIN" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(self)" },
];

// Bare apex → canonical www (docs/deployment.md, WP17). The load balancer routes pglive.in to this
// app rather than redirecting itself, so the 301 passes through the backend service that adds HSTS.
// Derived from SITE_URL at build time; nothing to do when SITE_URL has no "www." host.
function apexRedirects() {
  let canonical: URL;
  try {
    canonical = new URL(process.env.SITE_URL ?? "");
  } catch {
    return [];
  }
  if (!canonical.hostname.startsWith("www.")) return [];
  const apex = canonical.hostname.slice(4).replace(/\./g, "\\.");
  return [
    {
      source: "/:path*",
      has: [{ type: "host" as const, value: apex }],
      destination: `${canonical.origin}/:path*`,
      statusCode: 301 as const,
    },
  ];
}

const nextConfig: NextConfig = {
  // Self-contained server bundle for the production image (frontend/Dockerfile.prod).
  output: "standalone",
  async redirects() {
    return apexRedirects();
  },
  // Next 16's dev server refuses dev resources (the HMR socket) from any host but localhost, and
  // the page then renders but never hydrates: buttons do nothing. Anything else that opens the dev
  // server — an ngrok tunnel, a phone on the LAN — must be listed, e.g.
  // ALLOWED_DEV_ORIGINS=my-tunnel.ngrok-free.dev,192.168.1.4 (hosts only, no scheme or port).
  allowedDevOrigins: (process.env.ALLOWED_DEV_ORIGINS ?? "")
    .split(",")
    .map((origin) => origin.trim())
    .filter(Boolean),
  // The BFF proxy forwards Django paths verbatim, and Django's routes end in a slash
  // (POST can't follow APPEND_SLASH). Next would otherwise 308 `/api/v1/x/` to `/api/v1/x`.
  skipTrailingSlashRedirect: true,
  async headers() {
    return [
      { source: "/:path*", headers: SECURITY_HEADERS },
      // The QR file keeps one stable name, so cache it briefly rather than forever.
      { source: "/qr-app.svg", headers: [{ key: "Cache-Control", value: "public, max-age=3600" }] },
      // A cached worker script would pin users to old code; browsers must always revalidate it.
      {
        source: "/sw.js",
        headers: [
          { key: "Cache-Control", value: "no-cache, no-store, must-revalidate" },
          { key: "Service-Worker-Allowed", value: "/" },
        ],
      },
    ];
  },
  webpack: (config, { dev }) => {
    if (dev) {
      config.watchOptions = {
        poll: 1000,
        aggregateTimeout: 300,
      };
    }

    // Ensure next-intl/config alias is accurately resolved across both Webpack and Turbopack on Windows
    const requestConfigPath = path.resolve(__dirname, "src/i18n/request.ts");
    config.resolve = config.resolve || {};
    config.resolve.alias = config.resolve.alias || {};
    config.resolve.alias["next-intl/config$"] = requestConfigPath;
    config.resolve.alias["next-intl/config"] = requestConfigPath;

    return config;
  },
};

const config = withSerwist(withNextIntl(nextConfig));

// Build gate (the startup twin is src/instrumentation.ts): `next build` fails while
// the marketing site still has placeholder identity/app config. Use SITE_ENV=staging
// for builds that are not public. See docs/frontend-plan.md §12.
// (A function-form config receives the phase; process.env.NEXT_PHASE is set too late.)
export default function nextConfigWithLaunchGate(phase: string) {
  if (phase === PHASE_PRODUCTION_BUILD) {
    assertLaunchReady(process.env);
  }
  return config;
}


