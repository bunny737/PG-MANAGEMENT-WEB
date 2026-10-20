"use client";

import { User } from "lucide-react";
import { useTranslations } from "next-intl";
import { useSession } from "@/lib/session";

/** Phone dashboard greeting: "Welcome back," + the signed-in user's name, role chip and avatar. */
export function WelcomeCard() {
  const t = useTranslations("dashboard.phone");
  const tRoles = useTranslations("common.roles");
  const { userName, role } = useSession();
  const roleLabel = role === "owner" || role === "manager" || role === "receptionist" ? tRoles(role) : role;

  return (
    <section className="flex items-center justify-between gap-4 rounded-2xl border border-m3-primary/20 bg-m3-primary-container/40 p-4">
      <div className="min-w-0">
        <p className="text-base text-m3-on-surface-variant">{t("welcomeBack")}</p>
        <p className="truncate text-[22px] leading-7 font-bold text-m3-on-surface">{userName}</p>
        {roleLabel && (
          <span className="mt-2 inline-flex rounded-lg bg-m3-primary-container px-3 py-1 text-xs font-medium tracking-wide text-m3-primary uppercase">
            {roleLabel}
          </span>
        )}
      </div>
      <span className="flex size-16 shrink-0 items-center justify-center rounded-full bg-m3-primary text-m3-on-primary">
        <User className="size-8" aria-hidden />
      </span>
    </section>
  );
}
