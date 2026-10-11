"use client";

import { useCallback, useSyncExternalStore } from "react";
import { getCurrentUser, PERMISSIONS_KEY, type CurrentUser } from "@/lib/api";

export const SESSION_CHANGED_EVENT = "session-changed";

export interface SessionSnapshot {
  ready: boolean;
  authenticated: boolean;
  user: CurrentUser | null;
  role: string | null;
  permissions: string[];
  userName: string;
}

let inMemoryUser: CurrentUser | null = null;
let inFlightPromise: Promise<CurrentUser | null> | null = null;

function computeSnapshot(): SessionSnapshot {
  if (typeof window === "undefined") {
    return {
      ready: false,
      authenticated: false,
      user: null,
      role: null,
      permissions: [],
      userName: "",
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
  };
}

let cachedSnapshot: SessionSnapshot = computeSnapshot();
const listeners = new Set<() => void>();

function updateSnapshot() {
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
};

function getServerSnapshot(): SessionSnapshot {
  return SERVER_SNAPSHOT;
}

/**
 * Revalidates session from /auth/me/ exactly once per portal load. Guarded by a module-level
 * in-flight promise to collapse concurrent calls.
 */
export function ensureFreshSession(): Promise<CurrentUser | null> {
  if (typeof window === "undefined") return Promise.resolve(null);
  if (inFlightPromise) return inFlightPromise;

  inFlightPromise = getCurrentUser()
    .then((me) => {
      inMemoryUser = me;
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
      inFlightPromise = null;
    });

  return inFlightPromise;
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
    can,
  };
}
