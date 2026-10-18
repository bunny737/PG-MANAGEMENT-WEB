import type { NextConfig } from "next";
import { PHASE_PRODUCTION_BUILD } from "next/constants";
import createNextIntlPlugin from "next-intl/plugin";
import path from "path";
import { assertLaunchReady } from "./src/lib/site-config.validation";

const withNextIntl = createNextIntlPlugin();

// Safe baseline headers for every route. A Content-Security-Policy is deliberately
// NOT here yet: Razorpay Checkout, Google Maps, Firebase and the API origin all have
// to be inventoried and tried in report-only mode first (docs/frontend-plan.md §12).
const SECURITY_HEADERS = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-Frame-Options", value: "SAMEORIGIN" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(self)" },
];

const nextConfig: NextConfig = {
  async headers() {
    return [
      { source: "/:path*", headers: SECURITY_HEADERS },
      // The QR file keeps one stable name, so cache it briefly rather than forever.
      { source: "/qr-app.svg", headers: [{ key: "Cache-Control", value: "public, max-age=3600" }] },
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

const config = withNextIntl(nextConfig);

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


