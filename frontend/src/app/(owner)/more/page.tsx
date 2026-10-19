"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { ChevronRight, LogOut, User } from "lucide-react";
import { SIDEBAR_NAV_ITEMS } from "@/components/shared/NavItems";
import { InstallCard } from "@/features/pwa/InstallCard";
import { clearSession } from "@/lib/api";
import { useSession } from "@/lib/session";

export default function MorePage() {
  const router = useRouter();
  const t = useTranslations("common");
  const { can, ready, role, user, userName } = useSession();

  const visibleItems = SIDEBAR_NAV_ITEMS.filter(
    (item) => !item.permission || (ready && can(item.permission))
  );

  // The first 3 items are on the bottom nav; the remaining ones overflow here.
  const remainingItems = visibleItems.slice(3);

  const displayName = userName || (user ? `${user.first_name || ""} ${user.last_name || ""}`.trim() : "") || (role ? t(`roles.${role}`) : "");
  const roleLabel = role ? t(`roles.${role}`) : "";
  const initials = ((user?.first_name?.[0] || "") + (user?.last_name?.[0] || "")).toUpperCase() || (role ? role.slice(0, 2).toUpperCase() : "U");

  const handleLogout = async () => {
    await clearSession();
    router.replace("/login");
  };

  return (
    <main className="mx-auto w-full max-w-lg px-4 py-6 md:px-6">
      <div className="space-y-6">
        {/* User Card */}
        <div className="flex items-center gap-4 rounded-2xl border border-border bg-surface-card p-4 shadow-sm">
          <span className="flex size-12 shrink-0 items-center justify-center rounded-full bg-linear-to-br from-surface-inverse-soft to-surface-inverse text-sm font-bold text-ink-inverse">
            {initials}
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-base font-bold text-ink">{displayName}</h2>
            {roleLabel && (
              <span className="inline-block rounded-full bg-accent-soft px-2.5 py-0.5 text-xs font-semibold text-accent">
                {roleLabel}
              </span>
            )}
          </div>
          <Link
            href="/profile"
            className="flex items-center gap-1 rounded-xl border border-border bg-surface-page px-3 py-1.5 text-xs font-semibold text-ink hover:bg-surface-subtle transition-colors"
          >
            <User className="size-3.5" />
            <span>{t("labels.details")}</span>
          </Link>
        </div>

        {/* Overflow Navigation Items */}
        <div className="space-y-1 rounded-2xl border border-border bg-surface-card p-2 shadow-sm">
          <h3 className="px-3 py-2 text-xs font-bold uppercase tracking-wider text-ink-faint">
            {t("nav.more")}
          </h3>

          {remainingItems.map((item) => {
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className="flex items-center justify-between rounded-xl px-3 py-3 text-sm font-medium text-ink transition-colors hover:bg-surface-page"
              >
                <div className="flex items-center gap-3">
                  <span className="flex size-8 items-center justify-center rounded-lg bg-surface-subtle text-ink-muted">
                    <Icon className="size-4.5" />
                  </span>
                  <span>{t(item.labelKey)}</span>
                </div>
                <ChevronRight className="size-4 text-ink-faint" />
              </Link>
            );
          })}

          <Link
            href="/profile"
            className="flex items-center justify-between rounded-xl px-3 py-3 text-sm font-medium text-ink transition-colors hover:bg-surface-page"
          >
            <div className="flex items-center gap-3">
              <span className="flex size-8 items-center justify-center rounded-lg bg-surface-subtle text-ink-muted">
                <User className="size-4.5" />
              </span>
              <span>{t("labels.details")}</span>
            </div>
            <ChevronRight className="size-4 text-ink-faint" />
          </Link>
        </div>

        <InstallCard />

        {/* Sign Out Card / Action */}
        <div className="rounded-2xl border border-border bg-surface-card p-2 shadow-sm">
          <button
            onClick={handleLogout}
            className="flex w-full items-center justify-between rounded-xl px-3 py-3 text-sm font-semibold text-status-critical transition-colors hover:bg-status-critical-soft cursor-pointer"
          >
            <div className="flex items-center gap-3">
              <span className="flex size-8 items-center justify-center rounded-lg bg-status-critical-soft text-status-critical">
                <LogOut className="size-4.5" />
              </span>
              <span>{t("sideNav.signOut")}</span>
            </div>
            <ChevronRight className="size-4 text-status-critical/60" />
          </button>
        </div>
      </div>
    </main>
  );
}
