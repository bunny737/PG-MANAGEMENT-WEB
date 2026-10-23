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
import { initializeApp } from "firebase/app";
import { getMessaging, onBackgroundMessage } from "firebase/messaging/sw";
import { CACHE_SCOPE_HEADER } from "../lib/cacheScope";
import { isMarketingPath } from "../lib/marketingPaths";
import { pushTargetUrl } from "../lib/pushLinks";

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
  // cached so a visited screen can still open offline. The public marketing pages are not part
  // of the installed app and are never cached.
  {
    matcher: ({ request, sameOrigin, url }) =>
      sameOrigin && request.mode === "navigate" && !isMarketingPath(url.pathname),
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

// --- Web Push (docs/push-notifications-integration.md §6.3) ---------------------------------
// FCM "notification messages" are shown by the Firebase SDK itself when the app is in the
// background; this worker only adds the tap behaviour. The listener is registered BEFORE the
// SDK's own so it can stop the SDK's default handler from also opening a window.

self.addEventListener("notificationclick", (event) => {
  const fcm = (event.notification.data as { FCM_MSG?: { data?: { reference?: string } } } | null)?.FCM_MSG;
  if (!fcm) return; // not one of ours
  event.stopImmediatePropagation();
  event.notification.close();

  const target = new URL(pushTargetUrl(fcm.data?.reference), self.location.origin).href;
  event.waitUntil(
    (async () => {
      const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      const open = windows.find((client) => new URL(client.url).origin === self.location.origin);
      if (open) {
        // focus() can be refused (e.g. no recent user activation); the navigation must still happen.
        await open.focus().catch(() => {});
        await open.navigate(target).catch(() => {});
      } else {
        await self.clients.openWindow(target);
      }
    })()
  );
});

// The public identifiers only (they name the Firebase project; they authenticate nothing).
const firebaseConfig = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
  messagingSenderId: process.env.NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID,
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
};

if (Object.values(firebaseConfig).every(Boolean)) {
  // Registering a handler is what makes the SDK listen for pushes in this worker.
  onBackgroundMessage(getMessaging(initializeApp(firebaseConfig as Record<keyof typeof firebaseConfig, string>)), () => {});
}
