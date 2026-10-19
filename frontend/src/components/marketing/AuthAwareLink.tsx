"use client";

import { useEffect } from "react";
import Link from "next/link";
import { firstAllowedRoute } from "@/lib/permissions";
import { ensureFreshSession, useSession } from "@/lib/session";
import { cn } from "@/lib/utils";

// Roles that have a portal shell today (mirrors (owner)/layout.tsx). Resident
// and super_admin sessions have nowhere to land yet, so they keep seeing "Log in"
// instead of a button that would bounce them straight back out.
const PORTAL_ROLES = ["owner", "manager", "receptionist"];

/** "Log in" for visitors; "Open dashboard" only once `/auth/me/` has confirmed the
 * stored session in this page load (`validated` from the shared session store).
 * The cached localStorage flag alone is never trusted. Because `validated` lives in
 * the store, a failed first check recovers by itself when any later refresh (tab
 * focus, a 403) succeeds — no remount or reload needed. */
export function AuthAwareLink({
  loginLabel,
  dashboardLabel,
  className,
}: {
  loginLabel: string;
  dashboardLabel: string;
  className?: string;
}) {
  const { ready, authenticated, validated, role, permissions } = useSession();

  useEffect(() => {
    if (authenticated && !validated) void ensureFreshSession();
    // Not re-run on `validated`: a failed check must not retry in a loop; the store's
    // own focus/403 refreshes are the retry path.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authenticated]);

  const canOpen = ready && authenticated && validated && role !== null && PORTAL_ROLES.includes(role);
  const href = canOpen ? firstAllowedRoute(permissions) : "/login";

  return (
    <Link href={href} className={cn("text-sm font-semibold text-ink hover:text-accent", className)}>
      {canOpen ? dashboardLabel : loginLabel}
    </Link>
  );
}
