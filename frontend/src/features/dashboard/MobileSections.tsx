"use client";

import Link from "next/link";
import { ChevronRight, Clock, Landmark, TriangleAlert, BedDouble } from "lucide-react";
import { useTranslations } from "next-intl";
import { SummaryTile } from "@/components/mobile/SummaryTile";
import { TonalCard } from "@/components/mobile/TonalCard";
import { getActivityIconConfig, renderEmphasis } from "./TodaysActivity";
import type { ActiveIssue, ActivityItem, FinancialsSummary, OccupancySummary } from "./types";

/** Phone-only dashboard cards in the Android app's Material look. The desktop dashboard keeps its own
 * cards (OccupancyCard and friends); both are fed by the same queries in dashboard/page.tsx. */

function CardTitle({ icon, title, action }: { icon: React.ReactNode; title: string; action?: React.ReactNode }) {
  return (
    <div className="mb-4 flex items-center justify-between gap-3">
      <h2 className="flex min-w-0 items-center gap-3 text-[22px] leading-7 font-medium text-m3-on-surface">
        <span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-m3-primary-container text-m3-primary">
          {icon}
        </span>
        <span className="truncate">{title}</span>
      </h2>
      {action}
    </div>
  );
}

export function MobileOccupancyCard({ data }: { data: OccupancySummary }) {
  const t = useTranslations("dashboard.occupancy");
  const tPhone = useTranslations("dashboard.phone");
  const percent = Math.min(100, Math.max(0, data.occupiedPercent));

  return (
    <TonalCard className="p-5">
      <CardTitle
        icon={<BedDouble className="size-6" aria-hidden />}
        title={tPhone("occupancyTitle")}
        action={
          <Link href="/properties" className="shrink-0 text-base font-medium text-m3-primary">
            {tPhone("viewDetails")}
          </Link>
        }
      />
      <div className="grid grid-cols-3 gap-3">
        <SummaryTile className="flex-col items-start gap-1 px-3" tone="total" value={data.totalBeds} label={t("totalBeds")} />
        <SummaryTile
          className="flex-col items-start gap-1 px-3"
          tone="good"
          value={data.occupiedBeds}
          sublabel={`${data.occupiedPercent}%`}
          label={t("occupied")}
        />
        <SummaryTile
          className="flex-col items-start gap-1 px-3"
          tone="warn"
          value={data.vacantBeds}
          sublabel={`${data.vacantPercent}%`}
          label={t("vacant")}
        />
      </div>
      <div className="mt-5 border-t border-m3-outline-variant/60 pt-4">
        <div className="mb-2 flex items-center justify-between gap-3 text-base">
          <span className="text-m3-on-surface-variant">{t("capacityFilled")}</span>
          <span className="font-medium text-m3-on-surface">
            {t("capacitySubtitle", { occupied: data.occupiedBeds, total: data.totalBeds, percent: data.occupiedPercent })}
          </span>
        </div>
        <div
          role="progressbar"
          aria-label={t("bedsOccupied")}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent}
          className="h-2.5 overflow-hidden rounded-full bg-m3-surface-container"
        >
          <div className="h-full rounded-full bg-m3-primary" style={{ width: `${percent}%` }} />
        </div>
      </div>
    </TonalCard>
  );
}

export function MobileFinancialsCard({ data }: { data: FinancialsSummary }) {
  const t = useTranslations("dashboard.financials");
  const tPhone = useTranslations("dashboard.phone");

  return (
    <TonalCard className="border-transparent bg-m3-primary-container/40 p-5">
      <CardTitle
        icon={<Landmark className="size-6" aria-hidden />}
        title={tPhone("financialsTitle")}
        action={
          <Link href="/billing" className="shrink-0 text-base font-medium text-m3-primary">
            {t("viewBilling")}
          </Link>
        }
      />
      <p className="flex items-baseline gap-2 text-m3-on-surface">
        <span className="text-[34px] leading-10 font-bold">{data.monthlyRevenue}</span>
        <span className="text-base text-m3-on-surface-variant">{t("thisMonth")}</span>
      </p>
      <dl className="mt-4 space-y-2 border-t border-m3-outline-variant/60 pt-3 text-base">
        <Link href="/billing?status=outstanding" className="flex items-center justify-between gap-3">
          <dt className="text-m3-on-surface-variant">{t("outstandingDues")}</dt>
          <dd className="font-medium text-m3-critical">{data.outstandingDues}</dd>
        </Link>
        <div className="flex items-center justify-between gap-3">
          <dt className="text-m3-on-surface-variant">{t("securityDeposits")}</dt>
          <dd className="font-medium text-m3-on-surface">{data.securityDeposits}</dd>
        </div>
      </dl>
    </TonalCard>
  );
}

const ISSUE_STATUS_STYLE: Record<ActiveIssue["status"], string> = {
  open: "border-[#e57373]/50 bg-m3-critical-container text-m3-critical",
  in_progress: "border-[#e79a2e]/50 bg-m3-warn-container text-m3-warn",
  resolved: "border-[#5ca560]/50 bg-m3-good-container text-m3-good",
};

export function MobileIssuesCard({ issues, highPriorityCount }: { issues: ActiveIssue[]; highPriorityCount: number }) {
  const t = useTranslations("dashboard.issues");
  const tStatus = useTranslations("status");

  return (
    <TonalCard className="p-5">
      <CardTitle
        icon={<TriangleAlert className="size-6 text-m3-warn" aria-hidden />}
        title={t("title")}
        action={
          highPriorityCount > 0 ? (
            <span className="flex shrink-0 items-center gap-2 rounded-full border border-[#e57373]/50 bg-m3-critical-container px-3 py-1.5 text-base font-medium text-m3-critical">
              <span className="size-2 rounded-full bg-m3-critical" aria-hidden />
              {t("highShort", { count: highPriorityCount })}
            </span>
          ) : (
            <span className="shrink-0 text-base text-m3-on-surface-variant">{t("allClear")}</span>
          )
        }
      />
      {issues.length > 0 ? (
        <ul className="divide-y divide-m3-outline-variant/60">
          {issues.map((issue) => (
            <li key={issue.id} className="flex items-start gap-3 py-3">
              <span className="shrink-0 rounded-lg border border-m3-outline-variant bg-m3-surface-container-high px-3 py-2 text-sm leading-4 font-bold text-m3-on-surface">
                {issue.unit}
              </span>
              <p className="min-w-0 flex-1 text-base leading-6 text-m3-on-surface-variant">{issue.issue}</p>
              <span
                className={`shrink-0 rounded-full border px-3 py-1.5 text-sm font-medium ${ISSUE_STATUS_STYLE[issue.status]}`}
              >
                {tStatus(issue.status)}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="rounded-xl bg-m3-surface-container-high px-4 py-8 text-center text-base text-m3-on-surface-variant">
          {t("noIssues")}
        </p>
      )}
      <Link
        href="/complaints"
        className="mt-4 flex h-12 w-full items-center justify-center gap-1 rounded-xl border border-m3-outline-variant text-base font-medium text-m3-on-surface active:bg-m3-surface-container-high"
      >
        {t("viewAllComplaints").replace(/\s*[→›]\s*$/, "")}
        <ChevronRight className="size-5" aria-hidden />
      </Link>
    </TonalCard>
  );
}

export function MobileActivityCard({ items }: { items: ActivityItem[] }) {
  const t = useTranslations("dashboard.activity");
  const tPhone = useTranslations("dashboard.phone");

  return (
    <TonalCard className="p-5">
      <CardTitle icon={<Clock className="size-6" aria-hidden />} title={t("title")} />
      {items.length > 0 ? (
        <ul className="space-y-4">
          {items.map((item) => {
            const { icon: Icon, iconBg, iconColor } = getActivityIconConfig(item);
            return (
              <li key={item.id} className="flex items-start gap-3">
                <span className={`flex size-11 shrink-0 items-center justify-center rounded-full ${iconBg}`}>
                  <Icon className={`size-5 ${iconColor}`} aria-hidden />
                </span>
                <div className="min-w-0">
                  <p className="text-base leading-6 text-m3-on-surface">{renderEmphasis(item.text)}</p>
                  <p className="text-sm text-m3-on-surface-variant">{item.timestamp}</p>
                </div>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="py-6 text-center text-base text-m3-on-surface-variant">{tPhone("activityEmpty")}</p>
      )}
    </TonalCard>
  );
}
