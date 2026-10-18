"use client";

import { useCallback, useSyncExternalStore } from "react";
import {
  getCurrentUser,
  PERMISSION_DENIED_EVENT,
  PERMISSIONS_KEY,
  type CurrentUser,
} from "@/lib/api";

export const SESSION_CHANGED_EVENT = "session-changed";

export interface SessionSnapshot {
  ready: boolean;
  authenticated: boolean;
  user: CurrentUser | null;
  role: string | null;
  permissions: string[];
  userName: string;
  /** /auth/me/ has confirmed this session in the current page load (not just a cached
   * localStorage flag). False until the first successful refresh, and again after logout. */
  validated: boolean;
}

let inMemoryUser: CurrentUser | null = null;
let inFlightPromise: Promise<CurrentUser | null> | null = null;
/** Role of the last user /auth/me/ confirmed; null until then and after logout. */
let validatedRole: string | null = null;
/** Bumped every time the session is cleared; a response from an older generation is stale. */
let sessionGeneration = 0;

function computeSnapshot(): SessionSnapshot {
  if (typeof window === "undefined") {
    return {
      ready: false,
      authenticated: false,
      user: null,
      role: null,
      permissions: [],
      userName: "",
      validated: false,
    };
  }

  const isLoggedIn = localStorage.getItem("isLoggedIn") === "true";
  if (!isLoggedIn) {
    return {
      ready: true,
      authenticated: false,
      user: null,
      role: null,
      permissions: [],
      userName: "",
      validated: false,
    };
  }

  const role = localStorage.getItem("userRole");
  const rawPerms = localStorage.getItem(PERMISSIONS_KEY);
  const userName = localStorage.getItem("userName") || "";

  let permissions: string[] = [];
  let ready = false;

  if (rawPerms !== null) {
    try {
      const parsed = JSON.parse(rawPerms);
      if (Array.isArray(parsed)) {
        permissions = parsed;
        ready = true;
      }
    } catch {
      ready = false;
    }
  }

  let user: CurrentUser | null = inMemoryUser;
  if (!user) {
    const rawUser = localStorage.getItem("currentUser");
    if (rawUser) {
      try {
        user = JSON.parse(rawUser);
      } catch {
        user = null;
      }
    }
  }

  return {
    ready,
    authenticated: true,
    user,
    role,
    permissions,
    userName,
    validated: validatedRole !== null && validatedRole === role,
  };
}

let cachedSnapshot: SessionSnapshot = computeSnapshot();
const listeners = new Set<() => void>();

function updateSnapshot() {
  // A cleared session must not leave a confirmation behind for whoever logs in next.
  if (typeof window !== "undefined" && localStorage.getItem("isLoggedIn") !== "true") {
    validatedRole = null;
    inMemoryUser = null;
    // Invalidate any /auth/me/ still in flight, and let the next login start its own.
    sessionGeneration += 1;
    inFlightPromise = null;
  }
  cachedSnapshot = computeSnapshot();
  listeners.forEach((listener) => listener());
}

if (typeof window !== "undefined") {
  window.addEventListener(SESSION_CHANGED_EVENT, updateSnapshot);
  window.addEventListener("storage", updateSnapshot);
}

function subscribe(callback: () => void) {
  listeners.add(callback);
  return () => {
    listeners.delete(callback);
  };
}

function getSnapshot(): SessionSnapshot {
  return cachedSnapshot;
}

const SERVER_SNAPSHOT: SessionSnapshot = {
  ready: false,
  authenticated: false,
  user: null,
  role: null,
  permissions: [],
  userName: "",
  validated: false,
};

function getServerSnapshot(): SessionSnapshot {
  return SERVER_SNAPSHOT;
}

/** Minimum gap between *focus-triggered* refreshes of /auth/me/. */
const FOCUS_REFRESH_MIN_MS = 60_000;
/** A 403 refresh is never throttled by focus, only de-bounced so a burst of 403s is one fetch. */
const DENIED_REFRESH_DEBOUNCE_MS = 2_000;
let lastRefreshedAt = 0;
let lastDeniedRefreshAt = 0;

/**
 * Revalidates the session (and its permissions) from /auth/me/. Called once per portal load
 * by the layout, on tab focus (throttled, see `refreshOnFocus`) and after any 403 — the Owner
 * can change a staff member's module access at any time, and the API enforces that
 * immediately, but the UI only learns about it from here. Guarded by a module-level in-flight
 * promise to collapse concurrent calls.
 */
export function ensureFreshSession(): Promise<CurrentUser | null> {
  if (typeof window === "undefined") return Promise.resolve(null);
  if (inFlightPromise) return inFlightPromise;

  // A logout (or another tab's) while this request is pending bumps the generation;
  // the late answer must then be dropped, not written back over the cleared session.
  const generation = sessionGeneration;

  const promise: Promise<CurrentUser | null> = getCurrentUser()
    .then((me) => {
      if (generation !== sessionGeneration || !isLoggedIn()) return null;
      lastRefreshedAt = Date.now();
      inMemoryUser = me;
      validatedRole = me.role;
      localStorage.setItem("isLoggedIn", "true");
      localStorage.setItem("userRole", me.role);
      localStorage.setItem(PERMISSIONS_KEY, JSON.stringify(me.permissions ?? []));
      localStorage.setItem("userName", `${me.first_name ?? ''} ${me.last_name ?? ''}`.trim());
      localStorage.setItem("currentUser", JSON.stringify(me));
      updateSnapshot();
      return me;
    })
    .catch(() => {
      return null;
    })
    .finally(() => {
      // Only clear our own entry: after a logout a newer request may have replaced it.
      if (inFlightPromise === promise) inFlightPromise = null;
    });

  inFlightPromise = promise;
  return promise;
}

function isLoggedIn(): boolean {
  try {
    return localStorage.getItem("isLoggedIn") === "true";
  } catch {
    return false;
  }
}

function refreshOnFocus() {
  if (document.visibilityState === "hidden" || !isLoggedIn()) return;
  if (Date.now() - lastRefreshedAt < FOCUS_REFRESH_MIN_MS) return;
  void ensureFreshSession();
}

function refreshAfterDenied() {
  if (!isLoggedIn()) return;
  const now = Date.now();
  if (now - lastDeniedRefreshAt < DENIED_REFRESH_DEBOUNCE_MS) return;
  lastDeniedRefreshAt = now;
  void ensureFreshSession(); // deliberately not subject to FOCUS_REFRESH_MIN_MS
}

if (typeof window !== "undefined") {
  window.addEventListener("focus", refreshOnFocus);
  document.addEventListener("visibilitychange", refreshOnFocus);
  window.addEventListener(PERMISSION_DENIED_EVENT, refreshAfterDenied);
}

export function useSession() {
  const snapshot = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  const can = useCallback(
    (code: string) => {
      if (!snapshot.ready || !snapshot.authenticated) return false;
      return snapshot.permissions.includes(code);
    },
    [snapshot.ready, snapshot.authenticated, snapshot.permissions]
  );

  return {
    ready: snapshot.ready,
    authenticated: snapshot.authenticated,
    user: snapshot.user,
    role: snapshot.role,
    permissions: snapshot.permissions,
    userName: snapshot.userName,
    validated: snapshot.validated,
    can,
  };
}
