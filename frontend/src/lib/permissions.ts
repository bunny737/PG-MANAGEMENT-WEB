"use client";

import { SIDEBAR_NAV_ITEMS } from "@/components/shared/NavItems";
import { useSession } from "./session";

/**
 * Re-export usePermissions for backwards compatibility.
 * Prefer `useSession()` from `@/lib/session`.
 */
export function usePermissions() {
  const { ready, can } = useSession();
  return { ready, can };
}

/** Every signed-in user can reach their own profile, whatever their access. */
export const PROFILE_ROUTE = "/profile";

/**
 * Where to send a user who can't see the page they asked for (or just logged in): the first
 * nav destination their permissions allow, else their profile. Staff access is Owner-configured
 * per person (module access), so no screen can be assumed reachable by role.
 */
export function firstAllowedRoute(permissions: readonly string[], exclude?: string): string {
  const item = SIDEBAR_NAV_ITEMS.find(
    (entry) =>
      entry.href !== exclude && (!entry.permission || permissions.includes(entry.permission))
  );
  return item?.href ?? PROFILE_ROUTE;
}
