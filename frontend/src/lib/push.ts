// Web Push via Firebase Cloud Messaging (docs/push-notifications-integration.md §6).
//
// Browser-only. The Firebase SDK is imported lazily so it stays out of every page's bundle,
// and it reuses the Serwist service worker (app/sw.ts) instead of registering a second one.
// iOS (16.4+) only allows web push for an app added to the Home Screen, and only from a
// user tap — see getPushStatus() and enablePush().

import { apiFetch } from "@/lib/api";
import { isIos, isStandalone } from "@/lib/pwa";
import { registerPreLogoutStep } from "@/lib/sessionPurge";

const STORAGE_KEY = "pushSubscription"; // JSON { id, token }: the row this device registered
const SUBSCRIPTIONS_PATH = "/api/v1/notifications/push-subscriptions/";

export type PushStatus =
  | "unsupported"
  /** iOS, not installed: the push APIs don't exist until the app is on the Home Screen. */
  | "needs-install"
  | "blocked"
  | "off"
  | "on";

interface StoredSubscription {
  id: string;
  token: string;
}

function firebaseConfig() {
  const config = {
    apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
    projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
    messagingSenderId: process.env.NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID,
    appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
  };
  const vapidKey = process.env.NEXT_PUBLIC_FIREBASE_VAPID_KEY;
  return Object.values(config).every(Boolean) && vapidKey
    ? { app: config as Record<keyof typeof config, string>, vapidKey }
    : null;
}

function readStored(): StoredSubscription | null {
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null");
    return parsed && typeof parsed.id === "string" && typeof parsed.token === "string" ? parsed : null;
  } catch {
    return null;
  }
}

function writeStored(value: StoredSubscription | null) {
  try {
    if (value) localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Private mode: status just reads "off" next load.
  }
}

// --- reactive status (same pattern as lib/pwa.ts) -------------------------------------------

const listeners = new Set<() => void>();
const emit = () => listeners.forEach((listener) => listener());

export function subscribePushStatus(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getPushStatus(): PushStatus {
  if (typeof window === "undefined") return "unsupported";
  // The service worker (and so push) only exists in a production build.
  if (process.env.NODE_ENV !== "production" || !firebaseConfig()) return "unsupported";
  if (isIos() && !isStandalone()) return "needs-install";
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
    return "unsupported";
  }
  if (Notification.permission === "denied") return "blocked";
  return Notification.permission === "granted" && readStored() ? "on" : "off";
}

// --- Firebase ---------------------------------------------------------------------------

type FirebaseModules = readonly [typeof import("firebase/app"), typeof import("firebase/messaging")];

// Loaded lazily so the SDK stays out of every page's bundle.
let loadFirebase = (): Promise<FirebaseModules> => Promise.all([import("firebase/app"), import("firebase/messaging")]);

/** Test seam: the real SDK needs a service worker and FCM, neither of which exists in jsdom. */
export function setFirebaseLoader(loader: () => Promise<FirebaseModules>) {
  loadFirebase = loader;
}

async function firebase() {
  const config = firebaseConfig();
  if (!config) throw new Error("Firebase is not configured");
  const [app, messagingModule] = await loadFirebase();
  const instance = messagingModule.getMessaging(app.getApps()[0] ?? app.initializeApp(config.app));
  return { messaging: instance, vapidKey: config.vapidKey, sdk: messagingModule };
}

async function currentToken(): Promise<string> {
  const { messaging: instance, vapidKey, sdk } = await firebase();
  const registration = await navigator.serviceWorker.ready;
  const token = await sdk.getToken(instance, { vapidKey, serviceWorkerRegistration: registration });
  if (!token) throw new Error("No push token");
  return token;
}

// The push token belongs to the browser, not to an account, and logout only waits a few seconds
// for its cleanup — so the next account can start registering while the previous account's
// token revocation is still in flight. Two defences, because a stalled call cannot be cancelled:
//
//  1. Token operations are SERIALIZED: a registration waits for a revocation that has already
//     started, so the revocation can never land on the token it is about to create.
//  2. Each operation is capped at TOKEN_OP_TIMEOUT_MS so one hung SDK call cannot block pushes
//     for the rest of the page's life. If a revocation is abandoned that way and later completes
//     after a newer registration began (the epoch moved), it re-registers to repair the damage.
let tokenQueue: Promise<unknown> = Promise.resolve();
const TOKEN_OP_TIMEOUT_MS = 10_000;

function serialized<T>(operation: () => Promise<T>): Promise<T> {
  const run = tokenQueue.then(operation, operation);
  // The queue advances when the operation settles OR when it overstays, whichever is first.
  tokenQueue = Promise.race([
    run.catch(() => {}),
    new Promise<void>((resolve) => setTimeout(resolve, TOKEN_OP_TIMEOUT_MS)),
  ]);
  return run;
}

/** Bumped each time this browser starts registering, so a late cleanup can tell a newer
 * registration exists. */
let registrationEpoch = 0;

/** Registers (or re-registers) this device's token. The endpoint upserts, so calling it on
 * every start is safe; `replaces` drops the previous row if the browser rotated the token. */
function registerToken(): Promise<void> {
  return serialized(async () => {
    registrationEpoch += 1;
    const token = await currentToken();
    const previous = readStored();
    const subscription = await apiFetch<{ id: string }>(SUBSCRIPTIONS_PATH, {
      method: "POST",
      body: JSON.stringify({ fcm_token: token, device_type: "web", ...(previous ? { replaces: previous.id } : {}) }),
    });
    writeStored({ id: subscription.id, token });
  });
}

/** Turn notifications on. Must be called straight from a tap: iOS refuses the permission
 * prompt otherwise, so `requestPermission` is the first thing awaited. */
export async function enablePush(): Promise<PushStatus> {
  const permission = await Notification.requestPermission();
  if (permission === "granted") await registerToken();
  emit();
  return getPushStatus();
}

/** Unregister this device: server row first (needs the session), then the token itself at FCM
 * so a later user of this browser can't receive this user's pushes. Never throws. */
export async function disablePush(): Promise<void> {
  const startedAt = registrationEpoch;
  const stored = readStored();
  writeStored(null);
  emit();
  if (!stored) return;

  // Revoke the token FIRST. It is shared browser state and revoking it needs no session, so it
  // goes ahead of the server call, which can be slow. Serialized with registration (see above).
  try {
    await serialized(async () => {
      if (registrationEpoch !== startedAt) return; // a newer registration is already in place
      const { messaging: instance, sdk } = await firebase();
      await sdk.deleteToken(instance);
      // Abandoned after the timeout and finishing late: a registration began meanwhile and this
      // may have revoked its token, so make that registration again.
      if (registrationEpoch !== startedAt) void syncPush();
    });
  } catch {
    // Best-effort.
  }
  try {
    // skipAuth: a 401 here must not re-enter clearSession while a logout is waiting on us. If this
    // runs late it targets the old row by id, which another account's session cannot delete.
    await apiFetch(`${SUBSCRIPTIONS_PATH}${stored.id}/`, { method: "DELETE", skipAuth: true });
  } catch {
    // Offline or already gone; the token is already revoked.
  }
}

/** Once per app start: refreshes the registration (rotated token, last-seen) for a device that
 * already opted in. Silent — never prompts. */
export async function syncPush(): Promise<void> {
  if (getPushStatus() !== "on") return;
  try {
    await registerToken();
  } catch {
    // Offline or transient; tried again next start.
  }
}

export interface ForegroundPush {
  title: string;
  body: string;
  /** Screen to open, from the payload's `reference`. */
  reference: string;
}

/** Foreground messages are not shown by the browser, so the page shows its own toast. */
export async function onForegroundPush(listener: (push: ForegroundPush) => void): Promise<() => void> {
  const { messaging: instance, sdk } = await firebase();
  return sdk.onMessage(instance, (payload) =>
    listener({
      title: payload.notification?.title ?? "",
      body: payload.notification?.body ?? "",
      reference: payload.data?.reference ?? "",
    })
  );
}

// Unsubscribe on logout, before the cookies are cleared (lib/api.ts runs pre-logout steps first).
registerPreLogoutStep(disablePush);
