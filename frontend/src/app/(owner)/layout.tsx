"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { QueryClientProvider } from "@tanstack/react-query";
import { BottomNav } from "@/components/shared/BottomNav";
import { OfflineBanner } from "@/components/shared/OfflineBanner";
import { SideNav } from "@/components/shared/SideNav";
import { clearSession } from "@/lib/api";
import { queryClient } from "@/lib/queryClient";
import { ensureFreshSession, useSession } from "@/lib/session";

const ALLOWED_ROLES = ["owner", "manager", "receptionist"];

/**
 * Client-side UX guard for the (owner) portal layout.
 *
 * NOTE: This is explicitly a client-side UX guard, not a primary security boundary.
 * Real authorization boundaries reside on the backend via require_permission()
 * and JWT validation (see docs/frontend-plan.md §3.1).
 */
export default function OwnerLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const t = useTranslations("common");
  const { ready, authenticated, role } = useSession();

  // Revalidate session once per portal load.
  useEffect(() => {
    ensureFreshSession();
  }, []);

  useEffect(() => {
    if (!ready) return;

    if (!authenticated) {
      router.replace("/login");
      return;
    }

    if (role && !ALLOWED_ROLES.includes(role)) {
      // Rejects super_admin or resident accounts that have no portal shell here,
      // avoiding redirect loops by clearing session before bouncing to login.
      void (async () => {
        await clearSession();
        router.replace("/login");
      })();
    }
  }, [ready, authenticated, role, router]);

  const isAuthorized = ready && authenticated && role && ALLOWED_ROLES.includes(role);

  if (!isAuthorized) {
    return (
      <div className="flex min-h-screen w-full items-center justify-center bg-surface-page">
        <div className="flex flex-col items-center gap-2">
          <div className="size-8 animate-spin rounded-full border-4 border-accent border-t-transparent" />
          <p className="text-sm text-ink-muted">{t("authCheck")}</p>
        </div>
      </div>
    );
  }

  return (
    <QueryClientProvider client={queryClient}>
      <div className="flex min-h-screen">
        <SideNav />
        <div className="flex-1 pb-20 md:pb-0">
          <OfflineBanner />
          {children}
        </div>
        <BottomNav />
      </div>
    </QueryClientProvider>
  );
}
