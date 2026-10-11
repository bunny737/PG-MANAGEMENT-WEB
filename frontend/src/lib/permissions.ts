"use client";

import { useSession } from "./session";

/**
 * Re-export usePermissions for backwards compatibility.
 * Prefer `useSession()` from `@/lib/session`.
 */
export function usePermissions() {
  const { ready, can } = useSession();
  return { ready, can };
}
