"use client";

import { Bell, Building2, LogOut } from "lucide-react";
import { useTranslations } from "next-intl";
import { clearSession } from "@/lib/api";

/** Phone dashboard top bar (the desktop dashboard has DesktopHeader): logo tile, app name, bell, sign out. */
export function DashboardHeader() {
  const t = useTranslations("dashboard.header");
  const tCommon = useTranslations("common");

  return (
    <header className="sticky top-[var(--banner-h,0px)] z-20 flex min-h-16 items-center justify-between bg-m3-surface px-4 pt-[env(safe-area-inset-top)]">
      <div className="flex items-center gap-3">
        <span className="flex size-12 items-center justify-center rounded-2xl bg-m3-primary text-m3-on-primary">
          <Building2 className="size-6" aria-hidden />
        </span>
        <span className="text-[22px] leading-7 font-medium text-m3-on-surface">{tCommon("brandName")}</span>
      </div>
      <div className="flex items-center">
        <button
          type="button"
          aria-label={t("notifications")}
          className="flex size-12 cursor-pointer items-center justify-center rounded-full text-m3-on-surface active:bg-m3-surface-container-high"
        >
          <Bell className="size-6" aria-hidden />
        </button>
        <button
          type="button"
          aria-label={t("signOut")}
          onClick={async () => {
            await clearSession();
            window.location.href = "/login";
          }}
          title={t("signOut")}
          className="flex size-12 cursor-pointer items-center justify-center rounded-full text-m3-on-surface active:bg-m3-surface-container-high"
        >
          <LogOut className="size-6" aria-hidden />
        </button>
      </div>
    </header>
  );
}
