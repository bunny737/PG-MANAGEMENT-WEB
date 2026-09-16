"use client";

import { useEffect, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useAuth } from "./AuthContext";
import { roleHome } from "@/lib/roleHome";

interface RoleGuardProps {
  allowedRoles: string[];
  children: ReactNode;
}

/**
 * Waits for `/auth/me/` to resolve, then:
 * - no session → redirect to /login
 * - session, but role not in `allowedRoles` → redirect to that role's own
 *   group home (never renders this group's content for the wrong role)
 * - otherwise renders `children`
 *
 * Must be used inside an `AuthProvider`. Role checks always go through the
 * session fetched from the backend, never a client-guessed value.
 */
export function RoleGuard({ allowedRoles, children }: RoleGuardProps) {
  const router = useRouter();
  const t = useTranslations("common");
  const { user, isLoading } = useAuth();
  const authorized = !!user && allowedRoles.includes(user.role);

  useEffect(() => {
    if (isLoading) return;
    if (!user) {
      router.push("/login");
    } else if (!authorized) {
      router.push(roleHome(user.role));
    }
  }, [isLoading, user, authorized, router]);

  if (!authorized) {
    return (
      <div className="flex min-h-screen w-full items-center justify-center bg-surface-page">
        <div className="flex flex-col items-center gap-2">
          <div className="size-8 animate-spin rounded-full border-4 border-accent border-t-transparent" />
          <p className="text-sm text-ink-muted">{t("authCheck")}</p>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
