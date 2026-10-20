"use client";

import Link from "next/link";
import { BedDouble, Plus, Receipt, Wallet } from "lucide-react";
import { useTranslations } from "next-intl";
import { PermissionGate } from "@/components/shared/PermissionGate";
import { LAYOUT_ENTRY_PERMISSIONS } from "@/lib/layoutAccess";

const OUTLINED =
  "flex h-14 shrink-0 items-center gap-2 rounded-2xl border border-m3-outline-variant bg-m3-surface px-5 text-base font-medium text-m3-primary active:bg-m3-surface-container-high";

/**
 * Phone dashboard shortcuts, scrolling sideways like the Android app's. Each one is gated by the
 * permission of the screen it opens, so nobody sees a shortcut that would bounce them away.
 */
export function QuickActions() {
  const t = useTranslations("dashboard.quickActions");

  return (
    <div className="-mx-4 flex gap-3 overflow-x-auto px-4 pb-1">
      <PermissionGate permission="manage_admissions">
        <Link
          href="/admissions"
          className="flex h-14 shrink-0 items-center gap-2 rounded-2xl bg-m3-primary px-5 text-base font-medium text-m3-on-primary active:opacity-90"
        >
          <Plus className="size-5" aria-hidden />
          {t("addResident")}
        </Link>
      </PermissionGate>
      <PermissionGate anyOf={[...LAYOUT_ENTRY_PERMISSIONS]}>
        <Link href="/vacancies" className={OUTLINED}>
          <BedDouble className="size-5" aria-hidden />
          {t("vacancies")}
        </Link>
      </PermissionGate>
      <PermissionGate permission="view_finance">
        <Link href="/billing" className={OUTLINED}>
          <Receipt className="size-5" aria-hidden />
          {t("billing")}
        </Link>
      </PermissionGate>
      <PermissionGate permission="view_expenses">
        <Link href="/expenses" className={OUTLINED}>
          <Wallet className="size-5" aria-hidden />
          {t("expenses")}
        </Link>
      </PermissionGate>
    </div>
  );
}
