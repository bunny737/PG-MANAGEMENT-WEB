"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { QueryClientProvider } from "@tanstack/react-query";
import { BottomNav } from "@/components/shared/BottomNav";
import { OfflineBanner } from "@/components/shared/OfflineBanner";
import { PushRuntime } from "@/features/notifications/PushRuntime";
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
      <div className="flex min-h-dvh w-full items-center justify-center bg-surface-page">
        <div className="flex flex-col items-center gap-2">
          <div className="size-8 animate-spin rounded-full border-4 border-accent border-t-transparent" />
          <p className="text-sm text-ink-muted">{t("authCheck")}</p>
        </div>
      </div>
    );
  }

  return (
    <QueryClientProvider client={queryClient}>
      <div className="phone-ui flex min-h-dvh max-md:bg-m3-surface-page">
        <SideNav />
        {/* min-w-0: a flex item will not shrink below its content, so a horizontally scrolling row inside (the
            dashboard shortcuts, the filter chips) would otherwise widen the whole page past the screen. */}
        <div className="min-w-0 flex-1 pb-[calc(5rem+env(safe-area-inset-bottom))] md:pb-0">
          <OfflineBanner />
          {children}
        </div>
        <BottomNav />
        <PushRuntime />
      </div>
    </QueryClientProvider>
  );
}
