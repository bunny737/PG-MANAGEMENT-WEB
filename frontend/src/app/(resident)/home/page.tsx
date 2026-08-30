"use client";

import { useTranslations } from "next-intl";

// Placeholder landing page for the Resident portal (FE-01a scope is
// auth/routing only). Real content is FE-R1 scope per
// docs/frontend-plan.md §3.2 and §7.
export default function ResidentHomePage() {
  const t = useTranslations("common");

  return (
    <main className="flex min-h-screen w-full items-center justify-center bg-surface-page px-4">
      <p className="text-sm text-ink-muted">{t("labels.comingSoon")}</p>
    </main>
  );
}
