/// <reference lib="webworker" />
// Service worker (docs/frontend-plan.md §5.1), built by @serwist/next into public/sw.js.
//
// Offline is READ-ONLY by design: only GET requests are ever cached and nothing is queued
// for replay, so a payment or invoice can never be double-submitted by a reconnect.
//
// Tenant isolation (invariant F7): the app shell is precached (no tenant data) but every
// response that can hold tenant data goes into a cache named for the signed-in tenant+user,
// taken from the X-Cache-Scope header the page sets (lib/cacheScope.ts). No header, no
// caching. Logout also deletes every non-precache cache (lib/sessionPurge.ts).

import {
  ExpirationPlugin,
  NetworkFirst,
  NetworkOnly,
  CacheFirst,
  StaleWhileRevalidate,
  Serwist,
  type PrecacheEntry,
  type RouteHandlerCallbackOptions,
  type RuntimeCaching,
  type SerwistGlobalConfig,
  type SerwistPlugin,
} from "serwist";
import { CACHE_SCOPE_HEADER } from "../lib/cacheScope";

declare global {
  interface WorkerGlobalScope extends SerwistGlobalConfig {
    __SW_MANIFEST: (PrecacheEntry | string)[] | undefined;
  }
}

declare const self: ServiceWorkerGlobalScope;

const OFFLINE_URL = "/~offline";
/** Wait this long for the network before falling back to the cached copy. */
const NETWORK_TIMEOUT_SECONDS = 3;
/** How long an API response stays usable offline. Short on purpose: these are money screens. */
const API_CACHE_MAX_AGE_SECONDS = 5 * 60;

/** The installed app opens at /login?source=pwa; file it under /login so an offline launch finds the page. */
const normalisePageUrl: SerwistPlugin = {
  cacheKeyWillBeUsed: async ({ request }) => {
    const url = new URL(request.url);
    url.searchParams.delete("source");
    return url.href;
  },
};

/** Only cache a clean 200: never a redirect (a signed-out /dashboard redirects to /login and
 * would be cached under the wrong URL) and never a file download (receipts, exports). */
const cacheablePagesAndData: SerwistPlugin = {
  cacheWillUpdate: async ({ response }) => {
    if (response.status !== 200 || response.redirected) return null;
    if (response.headers.has("content-disposition")) return null;
    return response;
  },
};

const apiStrategies = new Map<string, NetworkFirst>();

function apiStrategyFor(scope: string) {
  let strategy = apiStrategies.get(scope);
  if (!strategy) {
    strategy = new NetworkFirst({
      cacheName: `api-${scope}`,
      networkTimeoutSeconds: NETWORK_TIMEOUT_SECONDS,
      plugins: [
        cacheablePagesAndData,
        new ExpirationPlugin({ maxEntries: 150, maxAgeSeconds: API_CACHE_MAX_AGE_SECONDS, purgeOnQuotaError: true }),
      ],
    });
    apiStrategies.set(scope, strategy);
  }
  return strategy;
}

const uncachedApi = new NetworkOnly();

const apiHandler = {
  handle: (options: RouteHandlerCallbackOptions) => {
    const scope = options.request.headers.get(CACHE_SCOPE_HEADER);
    return (scope ? apiStrategyFor(scope) : uncachedApi).handle(options);
  },
};

const runtimeCaching: RuntimeCaching[] = [
  // Signed-in API reads. `/api/auth/*` (login/logout) is deliberately outside this prefix.
  {
    matcher: ({ url, sameOrigin }) => sameOrigin && url.pathname.startsWith("/api/v1/"),
    handler: apiHandler,
  },
  // Hashed build output, including fonts (next/font self-hosts under /_next/static/media).
  {
    matcher: ({ url, sameOrigin }) => sameOrigin && url.pathname.startsWith("/_next/static/"),
    handler: new CacheFirst({
      cacheName: "next-static",
      plugins: [new ExpirationPlugin({ maxEntries: 200, maxAgeSeconds: 30 * 24 * 60 * 60 })],
    }),
  },
  // Same-origin images only. Property photos come from another origin and are tenant data,
  // so they are left to the browser's own HTTP cache rather than cached here.
  {
    matcher: ({ request, sameOrigin }) => sameOrigin && request.destination === "image",
    handler: new StaleWhileRevalidate({
      cacheName: "app-images",
      plugins: [new ExpirationPlugin({ maxEntries: 60, maxAgeSeconds: 30 * 24 * 60 * 60 })],
    }),
  },
  // Page documents: a shell with no tenant data (the signed-in screens render client-side),
  // cached so a visited screen can still open offline.
  {
    matcher: ({ request, sameOrigin }) => sameOrigin && request.mode === "navigate",
    handler: new NetworkFirst({
      cacheName: "pages",
      networkTimeoutSeconds: NETWORK_TIMEOUT_SECONDS,
      plugins: [normalisePageUrl, cacheablePagesAndData, new ExpirationPlugin({ maxEntries: 32 })],
    }),
  },
];

const serwist = new Serwist({
  precacheEntries: self.__SW_MANIFEST,
  // A new worker waits until the user taps "Reload" (features/pwa/PwaRegister.tsx), so an
  // update never swaps the code under a half-filled payment form. Serwist handles the
  // SKIP_WAITING message that the toast sends.
  skipWaiting: false,
  clientsClaim: true,
  runtimeCaching,
  fallbacks: {
    entries: [{ url: OFFLINE_URL, matcher: ({ request }) => request.destination === "document" }],
  },
});

serwist.addEventListeners();
