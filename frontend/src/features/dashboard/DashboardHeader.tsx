"use client";

import { Bell, Building2, LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { clearSession } from "@/lib/api";

export function DashboardHeader() {
  const t = useTranslations("dashboard.header");
  const tCommon = useTranslations("common");
  const router = useRouter();

  return (
    <header className="flex items-center justify-between px-4 py-4">
      <div className="flex items-center gap-2.5">
        <span className="flex size-9 items-center justify-center rounded-xl bg-linear-to-br from-accent to-accent-hover text-ink-inverse shadow-sm">
          <Building2 className="size-5" aria-hidden />
        </span>
        <span className="font-display text-lg font-extrabold text-ink">
          {tCommon("brandName")}
        </span>
      </div>
      <div className="flex items-center gap-1">
        <button
          type="button"
          aria-label={t("notifications")}
          className="relative flex size-9 items-center justify-center rounded-full text-ink-muted transition-colors hover:bg-surface-card hover:text-ink"
        >
          <Bell className="size-5" aria-hidden />
          <span className="absolute top-1.5 right-2 size-2 rounded-full bg-status-critical ring-2 ring-surface-page" />
        </button>
        <button
          type="button"
          aria-label={t("signOut")}
          onClick={() => {
            clearSession();
            router.push("/login");
          }}
          title={t("signOut")}
          className="flex size-9 cursor-pointer items-center justify-center rounded-full text-ink-muted transition-colors hover:bg-surface-card hover:text-ink"
        >
          <LogOut className="size-5" aria-hidden />
        </button>
      </div>
    </header>
  );
}
