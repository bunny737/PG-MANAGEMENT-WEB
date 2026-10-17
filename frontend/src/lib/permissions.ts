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
 * An access rule for `RequirePermission`/`PermissionGate`: exactly one of
 * a single `permission`, `anyOf` (entry permission — D2/D1's "any of"
 * rule: view_property_features OR manage_rooms_beds OR ...), or `allOf`
 * (a derived figure needing every constituent permission, e.g. D1's
 * `net_cash_flow` needing both view_finance and view_expenses).
 */
export type AccessRule =
  | { permission: string; anyOf?: never; allOf?: never }
  | { permission?: never; anyOf: string[]; allOf?: never }
  | { permission?: never; anyOf?: never; allOf: string[] };

/** Evaluates an `AccessRule` against `can()` from `useSession()`. */
export function hasAccess(can: (code: string) => boolean, rule: AccessRule): boolean {
  if (rule.permission) return can(rule.permission);
  if (rule.anyOf) return rule.anyOf.some(can);
  if (rule.allOf) return rule.allOf.every(can);
  return false;
}

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
