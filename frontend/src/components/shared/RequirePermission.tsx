"use client";

import React, { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { type AccessRule, firstAllowedRoute, hasAccess } from "@/lib/permissions";
import { useSession } from "@/lib/session";

type RequirePermissionProps = AccessRule & {
  /** Where to go when the permission is missing. Defaults to the first screen this user's
   * (Owner-configured) access allows, else their profile — never a hardcoded role landing page. */
  fallback?: string;
  children: React.ReactNode;
};

/**
 * Route-level guard: delays rendering children (and executing their effects/fetches)
 * until session readiness is confirmed. Redirects via router.replace() to fallback
 * if authorization check fails. Takes a single `permission`, or `anyOf`/`allOf` for
 * routes with a multi-permission entry rule (e.g. the property layout, D2/D1).
 */
export function RequirePermission({ fallback, children, ...rule }: RequirePermissionProps) {
  const router = useRouter();
  const pathname = usePathname();
  const t = useTranslations("common");
  const { ready, authenticated, can, permissions } = useSession();

  const hasPermission = ready && authenticated && hasAccess(can, rule);

  useEffect(() => {
    if (!ready) return;
    if (!authenticated) {
      router.replace("/login");
      return;
    }
    if (!hasAccess(can, rule)) {
      router.replace(fallback ?? firstAllowedRoute(permissions, pathname));
    }
    // `rule` is destructured from props each render, so its individual fields drive this effect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, authenticated, can, rule.permission, rule.anyOf, rule.allOf, fallback, permissions, pathname, router]);

  if (!ready || !hasPermission) {
    return (
      <div className="flex min-h-[50vh] w-full items-center justify-center">
        <div className="flex flex-col items-center gap-2">
          <div className="size-8 animate-spin rounded-full border-4 border-accent border-t-transparent" />
          <p className="text-sm text-ink-muted">{t("authCheck")}</p>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
