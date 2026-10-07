"use client";

import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { PERMISSIONS_KEY, getCurrentUser } from "@/lib/api";

const CHANGE_EVENT = "storage";

function subscribe(onChange: () => void) {
  window.addEventListener(CHANGE_EVENT, onChange);
  return () => window.removeEventListener(CHANGE_EVENT, onChange);
}

/**
 * Permission codes from `/auth/me/` (the backend's PERMISSION_MATRIX), so the
 * UI gates on what the server will actually allow instead of on role names.
 * `ready` is false until the list is known; `can()` is false until then.
 */
export function usePermissions() {
  const stored = useSyncExternalStore(
    subscribe,
    () => localStorage.getItem(PERMISSIONS_KEY),
    () => null
  );
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (stored !== null) return;
    let cancelled = false;
    // Sessions that logged in before permissions were cached at login.
    getCurrentUser()
      .then((me) => {
        localStorage.setItem(PERMISSIONS_KEY, JSON.stringify(me.permissions ?? []));
        window.dispatchEvent(new Event(CHANGE_EVENT));
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [stored]);

  const permissions = useMemo<string[] | null>(() => {
    if (stored === null) return failed ? [] : null;
    try {
      return JSON.parse(stored) as string[];
    } catch {
      return [];
    }
  }, [stored, failed]);

  return {
    ready: permissions !== null,
    can: (code: string) => Boolean(permissions?.includes(code)),
  };
}
