"use client";

import Link from "next/link";
import { FileText, Plus } from "lucide-react";
import { useTranslations } from "next-intl";

export function QuickActions() {
  const t = useTranslations("dashboard.quickActions");

  return (
    <div className="grid grid-cols-2 gap-3 px-4">
      <Link
        href="/admissions"
        className="flex items-center justify-center gap-2 rounded-xl bg-linear-to-br from-surface-inverse-soft to-surface-inverse px-4 py-3 text-sm font-semibold text-ink-inverse shadow-sm transition-colors hover:brightness-110"
      >
        <Plus className="size-4" aria-hidden />
        {t("addResident")}
      </Link>
      <Link
        href="/financials"
        className="flex items-center justify-center gap-2 rounded-xl border border-accent-border bg-surface-card px-4 py-3 text-sm font-semibold text-accent shadow-xs transition-colors hover:bg-accent-soft"
      >
        <FileText className="size-4" aria-hidden />
        {t("generateInvoices")}
      </Link>
    </div>
  );
}
