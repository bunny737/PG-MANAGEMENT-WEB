"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { ArrowDownLeft, Wallet } from "lucide-react";
import { getCashMovements } from "@/lib/api";
import { MoneyText } from "@/components/shared/MoneyText";
import { PropertyFilter, useActiveProperty } from "@/components/shared/PropertyFilter";
import { SectionError, SectionSkeleton } from "@/components/shared/SectionState";
import { queryKeys } from "@/lib/queryKeys";
import { currentMonthKey } from "@/lib/period";

export function CashMovementsList() {
  const t = useTranslations("billing.cashMovements");
  const tStatus = useTranslations("status");
  const { propertyId } = useActiveProperty();
  const [month, setMonth] = useState(currentMonthKey());

  const filters = { property: propertyId ?? undefined, month };
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: queryKeys.cashMovements.list(filters),
    queryFn: () => getCashMovements(filters),
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-border bg-surface-card p-4">
        <PropertyFilter />
        <input
          type="month"
          value={month}
          onChange={(event) => setMonth(event.target.value)}
          className="rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
        />
      </div>

      {isLoading && <SectionSkeleton className="h-64" />}
      {isError && <SectionError onRetry={() => refetch()} message={t("errLoadFailed")} />}

      {data && (
        <>
          <div className="grid grid-cols-3 gap-3">
            <div className="rounded-2xl border border-border bg-surface-card p-4">
              <p className="text-xs font-semibold uppercase tracking-wider text-ink-faint">{t("grossReceipts")}</p>
              <MoneyText value={data.gross_receipts} className="text-xl font-bold text-ink" />
            </div>
            <div className="rounded-2xl border border-border bg-surface-card p-4">
              <p className="text-xs font-semibold uppercase tracking-wider text-ink-faint">{t("refundsPaid")}</p>
              <MoneyText value={data.refunds_paid} className="text-xl font-bold text-ink" />
            </div>
            <div className="rounded-2xl border border-border bg-surface-card p-4">
              <p className="text-xs font-semibold uppercase tracking-wider text-ink-faint">{t("total")}</p>
              <MoneyText value={data.total} className="text-xl font-bold text-ink" />
            </div>
          </div>

          {data.results.length === 0 ? (
            <div className="flex flex-col items-center gap-2 rounded-2xl border border-border bg-surface-card p-12 text-center">
              <Wallet className="size-8 text-ink-faint" />
              <h3 className="text-sm font-bold text-ink">{t("emptyTitle")}</h3>
              <p className="text-xs text-ink-muted">{t("emptyDesc")}</p>
            </div>
          ) : (
            <div className="overflow-hidden rounded-2xl border border-border bg-surface-card">
              <div className="hidden grid-cols-12 gap-4 border-b border-border bg-surface-page px-5 py-3 text-xs font-bold uppercase tracking-wider text-ink-muted md:grid">
                <div className="col-span-3">{t("table.date")}</div>
                <div className="col-span-4">{t("table.resident")}</div>
                <div className="col-span-2 text-right">{t("table.amount")}</div>
                <div className="col-span-2">{t("table.mode")}</div>
                <div className="col-span-1">{t("table.receipt")}</div>
              </div>
              <div className="divide-y divide-border">
                {data.results.map((row) => (
                  <div key={row.id} className="grid grid-cols-1 gap-2 px-5 py-3.5 text-sm md:grid-cols-12 md:items-center md:gap-4">
                    <div className="col-span-3 flex items-center gap-1.5 text-ink-muted">
                      <ArrowDownLeft className="size-3.5 text-status-good" />
                      {row.date}
                    </div>
                    <div className="col-span-4 font-medium text-ink">{row.resident_name}</div>
                    <div className="col-span-2 text-right">
                      <MoneyText value={row.amount} />
                    </div>
                    <div className="col-span-2 text-ink-muted">{tStatus(row.payment_mode)}</div>
                    <div className="col-span-1 text-ink-muted">{row.receipt_number ?? "—"}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
