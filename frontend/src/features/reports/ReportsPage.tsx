"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { getAnalyticsSummary, getAnalyticsTrend } from "@/lib/api";
import { MoneyText } from "@/components/shared/MoneyText";
import { MonthNavigator } from "@/components/shared/MonthNavigator";
import { PropertyFilter, useActiveProperty } from "@/components/shared/PropertyFilter";
import { SectionError, SectionSkeleton } from "@/components/shared/SectionState";
import { currentMonthKey } from "@/lib/period";
import { queryKeys } from "@/lib/queryKeys";
import { useSession } from "@/lib/session";
import { cn } from "@/lib/utils";
import { TrendChart } from "./TrendChart";
import { ExportsTab } from "./ExportsTab";

const TABS = ["overview", "collections", "occupancy", "exports"] as const;
type Tab = (typeof TABS)[number];

function Card({ label, children, highlight }: { label: string; children: React.ReactNode; highlight?: boolean }) {
  return (
    <div className="rounded-2xl border border-border bg-surface-card p-4">
      <p className="text-[10px] uppercase tracking-wider text-ink-faint">{label}</p>
      <div className={cn("mt-1 text-lg font-bold", highlight && "text-status-critical")}>{children}</div>
    </div>
  );
}

export function ReportsPage() {
  const t = useTranslations("reports");
  const tCards = useTranslations("reports.cards");
  const router = useRouter();
  const searchParams = useSearchParams();
  const { can } = useSession();
  const { propertyId } = useActiveProperty();
  const [month, setMonth] = useState(currentMonthKey());
  const activeTab = (searchParams.get("tab") as Tab) ?? "overview";

  function setTab(tab: Tab) {
    const params = new URLSearchParams(searchParams);
    params.set("tab", tab);
    router.push(`/reports?${params.toString()}`);
  }

  const summaryQuery = useQuery({
    queryKey: queryKeys.analytics.summary({ property: propertyId, month }),
    queryFn: () => getAnalyticsSummary({ property: propertyId ?? undefined, month }),
  });
  const trendQuery = useQuery({
    queryKey: queryKeys.analytics.trend({ property: propertyId, end: month }),
    queryFn: () => getAnalyticsTrend({ property: propertyId ?? undefined, end: month, months: "6" }),
    enabled: activeTab === "overview",
  });

  const summary = summaryQuery.data;
  const canFinance = can("view_finance");

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-ink">{t("title")}</h1>
          <p className="text-sm text-ink-muted">{t("subtitle")}</p>
        </div>
        <div className="flex gap-2">
          <MonthNavigator value={month} onChange={setMonth} />
          <PropertyFilter />
        </div>
      </div>

      <div className="flex gap-2 overflow-x-auto border-b border-border">
        {TABS.map((tab) => {
          if (tab === "collections" && !canFinance) return null;
          return (
            <button
              key={tab}
              type="button"
              onClick={() => setTab(tab)}
              className={cn(
                "shrink-0 border-b-2 px-3 py-2.5 text-sm font-semibold transition-colors cursor-pointer",
                activeTab === tab ? "border-accent text-accent" : "border-transparent text-ink-muted hover:text-ink"
              )}
            >
              {t(`tabs.${tab}`)}
            </button>
          );
        })}
      </div>

      {summaryQuery.isLoading && <SectionSkeleton className="h-64" />}
      {summaryQuery.isError && <SectionError onRetry={() => summaryQuery.refetch()} message={t("errLoadFailed")} />}

      {summary && summary.timezones.length > 1 && (
        <p className="rounded-xl bg-surface-subtle px-3 py-2 text-xs text-ink-muted">{t("mixedTimezones")}</p>
      )}

      {summary && activeTab === "overview" && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {summary.finance && (
              <>
                <a href={`/billing?property=${propertyId ?? ""}&status=outstanding`}>
                  <Card label={`${tCards("cashCollected")}`}>
                    <MoneyText value={summary.finance.cash_collected} />
                  </Card>
                </a>
                <a href={`/billing?property=${propertyId ?? ""}&status=outstanding`}>
                  <Card label={`${tCards("outstandingTotal")} (${t("currentBalance")})`} highlight={Number(summary.finance.outstanding_total) > 0}>
                    <MoneyText value={summary.finance.outstanding_total} />
                  </Card>
                </a>
                <Card label={tCards("collectionRate")}>
                  {summary.finance.collection_rate === null ? "—" : `${summary.finance.collection_rate}%`}
                </Card>
              </>
            )}
            {summary.expenses && (
              <a href={`/expenses?month=${month}`}>
                <Card label={tCards("expensesPaid")}>
                  <MoneyText value={summary.expenses.expenses_paid} />
                </Card>
              </a>
            )}
            {summary.cash_flow && (
              <Card label={tCards("netCashFlow")}>
                <MoneyText value={summary.cash_flow.net_cash_flow} />
              </Card>
            )}
          </div>

          {summary.finance && (
            <p className="text-xs text-ink-muted">
              {tCards("ytd")} ({summary.ytd.start} – {summary.ytd.end}, {t("toDate")}):{" "}
              <MoneyText value={summary.finance.ytd_cash_collected} />
            </p>
          )}

          <div className="rounded-2xl border border-border bg-surface-card p-5">
            <h2 className="mb-3 text-sm font-bold text-ink">{t("trend.title")}</h2>
            {trendQuery.isLoading && <SectionSkeleton className="h-64" />}
            {trendQuery.isError && <SectionError onRetry={() => trendQuery.refetch()} />}
            {trendQuery.data && <TrendChart trend={trendQuery.data} />}
          </div>
        </div>
      )}

      {summary?.finance && activeTab === "collections" && canFinance && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Card label={tCards("grossReceipts")}><MoneyText value={summary.finance.gross_receipts} /></Card>
          <Card label={tCards("refundsPaid")}><MoneyText value={summary.finance.refunds_paid} /></Card>
          <Card label={tCards("cashCollected")}><MoneyText value={summary.finance.cash_collected} /></Card>
          <a href={`/billing?property=${propertyId ?? ""}&period=${month}`}>
            <Card label={`${tCards("periodInvoiced")} (${t("toDate")})`}>
              <MoneyText value={summary.finance.period_invoiced} />
            </Card>
          </a>
          <a href={`/billing?property=${propertyId ?? ""}&period=${month}`}>
            <Card label={`${tCards("periodCollected")} (${t("toDate")})`}>
              <MoneyText value={summary.finance.period_collected} />
            </Card>
          </a>
          <a href={`/billing?property=${propertyId ?? ""}&period=${month}&status=outstanding`}>
            <Card label={`${tCards("periodOutstanding")} (${t("currentBalance")})`}>
              <MoneyText value={summary.finance.period_outstanding} />
            </Card>
          </a>
          <a href={`/billing?property=${propertyId ?? ""}&status=overdue`}>
            <Card label={`${tCards("overdueTotal")} (${t("currentBalance")})`} highlight={Number(summary.finance.overdue_total) > 0}>
              <MoneyText value={summary.finance.overdue_total} />
            </Card>
          </a>
          <Card label={tCards("depositsHeld")}><MoneyText value={summary.finance.deposits_held} /></Card>
        </div>
      )}

      {summary && activeTab === "occupancy" && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          <Card label={tCards("totalBeds")}>{summary.occupancy.total}</Card>
          <Card label={tCards("occupied")}>{summary.occupancy.occupied}</Card>
          <Card label={tCards("available")}>{summary.occupancy.available}</Card>
          <Card label={tCards("reserved")}>{summary.occupancy.reserved}</Card>
          <Card label={tCards("maintenance")}>{summary.occupancy.maintenance}</Card>
          <div className="col-span-2 sm:col-span-5">
            <Card label={tCards("occupancyRate")}>
              {summary.occupancy.occupancy_rate === null
                ? summary.occupancy.total === 0
                  ? tCards("noBedsYet")
                  : tCards("allUnderMaintenance")
                : `${summary.occupancy.occupancy_rate}%`}
            </Card>
          </div>
        </div>
      )}

      {activeTab === "exports" && <ExportsTab month={month} propertyId={propertyId} />}
    </div>
  );
}
