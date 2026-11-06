"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { AlertTriangle, ChevronRight, Lock, Plus, UtensilsCrossed } from "lucide-react";
import { EmptyState } from "@/components/shared/EmptyState";
import { MoneyText } from "@/components/shared/MoneyText";
import { PermissionGate } from "@/components/shared/PermissionGate";
import { useActiveProperty } from "@/components/shared/PropertyFilter";
import { SectionError, SectionSkeleton } from "@/components/shared/SectionState";
import { StatusPill } from "@/components/shared/StatusPill";
import { listFoodHolidays } from "@/lib/api";
import { formatDate } from "@/lib/date";
import { queryKeys } from "@/lib/queryKeys";
import { FoodHolidayFormSheet } from "./FoodHolidayFormSheet";

export function FoodHolidaysList() {
  const t = useTranslations("notices");
  const { propertyId } = useActiveProperty();
  const [showForm, setShowForm] = useState(false);

  const filters = { property: propertyId ?? undefined };
  const { data: holidays = [], isLoading, isError, refetch } = useQuery({
    queryKey: queryKeys.notices.holidays(filters),
    queryFn: () => listFoodHolidays(filters),
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-xl text-sm text-ink-muted">{t("holidays.intro")}</p>
        <PermissionGate permission="manage_notices">
          <button
            type="button"
            onClick={() => setShowForm(true)}
            className="inline-flex items-center gap-1.5 rounded-xl bg-accent px-3 py-2 text-sm font-semibold text-ink-inverse transition-colors hover:bg-accent-hover cursor-pointer"
          >
            <Plus className="size-4" />
            {t("holidays.add")}
          </button>
        </PermissionGate>
      </div>

      {isLoading && <SectionSkeleton className="h-64" />}
      {isError && <SectionError onRetry={() => refetch()} message={t("holidays.errLoadFailed")} />}

      {!isLoading && !isError && holidays.length === 0 && (
        <EmptyState icon={UtensilsCrossed} title={t("holidays.emptyTitle")} body={t("holidays.emptyDesc")} />
      )}

      {!isLoading && !isError && holidays.length > 0 && (
        <div className="space-y-3">
          {holidays.map((holiday) => (
            <div key={holiday.id} className="overflow-hidden rounded-2xl border border-border bg-surface-card">
              <Link
                href={`/notices/holidays/${holiday.id}`}
                className="flex items-center justify-between gap-3 px-5 py-4 transition-colors hover:bg-surface-page"
              >
                <div className="min-w-0 flex-1 space-y-1.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-base font-bold text-ink">{holiday.name}</h3>
                    <StatusPill
                      label={holiday.adjust_in_bill ? t("holidays.adjusted") : t("holidays.notAdjusted")}
                      tone={holiday.adjust_in_bill ? "accent" : "neutral"}
                    />
                    {holiday.is_locked && (
                      <span className="inline-flex items-center gap-1 text-xs font-semibold text-ink-muted">
                        <Lock className="size-3" aria-hidden />
                        {t("holidays.locked")}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-ink-muted">
                    {formatDate(holiday.start_date)} – {formatDate(holiday.end_date)} ·{" "}
                    {t("holidays.days", { count: holiday.total_days })}
                    {!propertyId && ` · ${holiday.property_name}`}
                  </p>
                </div>
                {holiday.credit_total !== undefined && holiday.adjust_in_bill && (
                  <div className="text-right text-sm">
                    <MoneyText value={holiday.credit_total} className="font-semibold text-ink" />
                    <p className="text-xs text-ink-muted">{t("holidays.credited", { count: holiday.credit_count ?? 0 })}</p>
                  </div>
                )}
                <ChevronRight className="size-4 shrink-0 text-ink-faint" aria-hidden />
              </Link>
              {holiday.notice_outdated && holiday.announcement && (
                <Link
                  href={`/notices?tab=notices&notice=${holiday.announcement}`}
                  className="flex items-center gap-2 border-t border-border bg-status-warn-soft px-5 py-2 text-xs font-semibold text-status-warn hover:opacity-90"
                >
                  <AlertTriangle className="size-3.5 shrink-0" aria-hidden />
                  {t("holidays.noticeOutdated")}
                </Link>
              )}
            </div>
          ))}
        </div>
      )}

      {showForm && <FoodHolidayFormSheet defaultProperty={propertyId} onClose={() => setShowForm(false)} />}
    </div>
  );
}
