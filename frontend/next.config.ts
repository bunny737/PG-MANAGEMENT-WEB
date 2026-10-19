import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";
import withSerwistInit from "@serwist/next";
import { randomUUID } from "node:crypto";
import path from "path";

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

const nextConfig: NextConfig = {
  // The BFF proxy forwards Django paths verbatim, and Django's routes end in a slash
  // (POST can't follow APPEND_SLASH). Next would otherwise 308 `/api/v1/x/` to `/api/v1/x`.
  skipTrailingSlashRedirect: true,
  async headers() {
    return [
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

export default withSerwist(withNextIntl(nextConfig));


