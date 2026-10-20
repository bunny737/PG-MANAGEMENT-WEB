"use client";

import React, { Suspense, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { ActiveIssuesCard } from "@/features/dashboard/ActiveIssuesCard";
import { DashboardHeader } from "@/features/dashboard/DashboardHeader";
import { InstallNudge } from "@/features/pwa/InstallNudge";
import { PropertyPill } from "@/components/mobile/PropertyPill";
import { WelcomeCard } from "@/features/dashboard/WelcomeCard";
import {
  MobileActivityCard,
  MobileFinancialsCard,
  MobileIssuesCard,
  MobileOccupancyCard,
} from "@/features/dashboard/MobileSections";
import { formatDate, isLocalToday } from "@/lib/date";
import { DesktopHeader } from "@/features/dashboard/DesktopHeader";
import { FinancialsCard } from "@/features/dashboard/FinancialsCard";
import { OccupancyCard } from "@/features/dashboard/OccupancyCard";
import { QuickActions } from "@/features/dashboard/QuickActions";
import { TodaysActivity } from "@/features/dashboard/TodaysActivity";
import {
  getAnalyticsSummary,
  listAdmissions,
  listComplaints,
  listPaymentsFiltered,
  listResidents,
} from "@/lib/api";
import { RequirePermission } from "@/components/shared/RequirePermission";
import { SectionError, SectionSkeleton } from "@/components/shared/SectionState";
import { useActiveProperty } from "@/components/shared/PropertyFilter";
import { formatMoney } from "@/lib/money";
import { currentMonthKey } from "@/lib/period";
import { queryKeys } from "@/lib/queryKeys";
import { useSession } from "@/lib/session";
import type { ActiveIssue, ActivityItem } from "@/features/dashboard/types";

function DashboardContent() {
  const t = useTranslations("dashboard");
  const { can } = useSession();
  const { propertyId } = useActiveProperty();
  const canSeeFinance = can("view_finance");
  const canSeeComplaints = can("manage_complaints");
  const canSeeAdmissions = can("manage_admissions");
  const canSeeResidents = can("view_resident_profile");
  const month = currentMonthKey();

  // D0/D1: occupancy + financials come from one server-computed summary —
  // no client-side summing of invoice/payment lists (invariant F1).
  const summaryQuery = useQuery({
    queryKey: queryKeys.analytics.summary({ property: propertyId, month }),
    queryFn: () => getAnalyticsSummary({ property: propertyId ?? undefined, month }),
  });

  // Section-state rule: no permission -> the query is simply disabled, so
  // nothing is fetched and nothing renders for it; a real error gets its
  // own retry, never silently swallowed into an empty list.
  // Every section follows the property selector, not just the summary above: the property is part of
  // each key, so switching it refetches instead of showing another property's rows from the cache.
  const property = propertyId ?? undefined;
  const complaintsQuery = useQuery({
    queryKey: ["dashboard", "complaints", propertyId],
    queryFn: () => listComplaints({ property }),
    enabled: canSeeComplaints,
  });
  const admissionsQuery = useQuery({
    queryKey: ["dashboard", "admissions", propertyId],
    queryFn: () => listAdmissions({ property }),
    enabled: canSeeAdmissions,
  });
  const residentsQuery = useQuery({
    queryKey: ["dashboard", "residents", propertyId],
    queryFn: () => listResidents(property),
    enabled: canSeeResidents,
  });
  const paymentsQuery = useQuery({
    queryKey: ["dashboard", "payments", month, propertyId],
    queryFn: () => listPaymentsFiltered({ month, property }),
    enabled: canSeeFinance,
  });

  const { activity, todayActivity } = useMemo<{ activity: ActivityItem[]; todayActivity: ActivityItem[] }>(() => {
    const admissions = admissionsQuery.data ?? [];
    const residents = residentsQuery.data ?? [];
    const payments = paymentsQuery.data ?? [];
    const complaints = complaintsQuery.data ?? [];

    // iso is the raw API value: a date-only string (joining/payment date) or a full timestamp (complaint).
    const feed: Array<{ id: string; tone: ActivityItem["tone"]; text: string; date: Date; iso: string }> = [];

    admissions.forEach((a) => {
      const r = residents.find((res) => res.id === a.resident);
      const name = r ? `${r.first_name} ${r.last_name || ""}`.trim() : t("activity.residentFallback");
      const room = r?.unit || t("activity.roomFallback");
      feed.push({
        id: `adm-${a.id}`,
        tone: "info",
        text: t("activity.checkedIn", { name, room }),
        date: new Date(a.joining_date),
        iso: a.joining_date,
      });
    });

    payments.forEach((p) => {
      feed.push({
        id: `pay-${p.id}`,
        tone: "good",
        text: t("activity.paymentReceived", {
          room: p.room_number ?? t("activity.roomFallback"),
          amount: formatMoney(p.amount),
        }),
        date: new Date(p.payment_date),
        iso: p.payment_date,
      });
    });

    complaints.forEach((c) => {
      feed.push({
        id: `comp-${c.id}`,
        tone: "neutral",
        text: t("activity.complaintLogged", {
          room: c.resident_details?.unit || t("activity.roomFallback"),
          category: c.category.replace("_", " "),
        }),
        date: new Date(c.created_at),
        iso: c.created_at,
      });
    });

    const sorted = feed.sort((a, b) => b.date.getTime() - a.date.getTime());
    return {
      // Desktop: the latest five, whatever day they happened.
      activity: sorted.slice(0, 5).map(({ id, tone, text, date }) => ({
        id,
        tone,
        text,
        timestamp: formatDate(date),
      })),
      // Phone: only what happened on the device's local calendar day, so the section name is truthful.
      todayActivity: sorted
        .filter(({ iso }) => isLocalToday(iso))
        .slice(0, 8)
        .map(({ id, tone, text, date, iso }) => ({
          id,
          tone,
          text,
          timestamp: iso.includes("T")
            ? date.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" })
            : formatDate(iso),
        })),
    };
  }, [admissionsQuery.data, residentsQuery.data, paymentsQuery.data, complaintsQuery.data, t]);

  // The phone activity card is built from up to four queries. Until the ones this user can read have settled
  // it must not claim "No activity today", and if one failed the feed is incomplete, not empty.
  const activitySources = [
    canSeeAdmissions && admissionsQuery,
    canSeeResidents && residentsQuery,
    canSeeFinance && paymentsQuery,
    canSeeComplaints && complaintsQuery,
  ].filter((query) => query !== false);
  const activityFailed = activitySources.filter((query) => query.isError);
  const activityPending = activityFailed.length === 0 && activitySources.some((query) => query.isPending);

  const issues = useMemo<ActiveIssue[]>(() => {
    const complaints = complaintsQuery.data ?? [];
    return complaints
      .filter((c) => c.status === "open" || c.status === "assigned" || c.status === "in_progress")
      .slice(0, 3)
      .map((c) => ({
        id: c.id,
        unit: c.resident_details?.unit || t("activity.roomFallback"),
        issue: c.description,
        status: c.status === "assigned" ? ("open" as const) : (c.status as "open" | "in_progress" | "resolved"),
      }));
  }, [complaintsQuery.data, t]);

  const highPriorityCount = (complaintsQuery.data ?? []).filter(
    (c) => (c.status === "open" || c.status === "assigned" || c.status === "in_progress") &&
      (c.priority === "high" || c.priority === "urgent")
  ).length;

  const summary = summaryQuery.data;
  const occupancy = summary
    ? {
        totalBeds: summary.occupancy.total,
        occupiedBeds: summary.occupancy.occupied,
        vacantBeds: summary.occupancy.available,
        occupiedPercent: summary.occupancy.occupancy_rate ?? 0,
        vacantPercent:
          summary.occupancy.total > 0
            ? Math.round((summary.occupancy.available / summary.occupancy.total) * 1000) / 10
            : 0,
      }
    : null;
  const financials = summary?.finance
    ? {
        monthlyRevenue: formatMoney(summary.finance.cash_collected),
        outstandingDues: formatMoney(summary.finance.outstanding_total),
        securityDeposits: formatMoney(summary.finance.deposits_held),
      }
    : null;

  return (
    <>
      {/* Mobile */}
      <div className="mx-auto flex max-w-md flex-col gap-4 pb-6 md:hidden">
        <DashboardHeader />
        <div className="flex flex-col gap-4 px-4">
          <InstallNudge />
          <PropertyPill wide />
          <WelcomeCard />
          <QuickActions />
          {summaryQuery.isLoading && <SectionSkeleton className="h-40" />}
          {summaryQuery.isError && <SectionError onRetry={() => summaryQuery.refetch()} />}
          {occupancy && <MobileOccupancyCard data={occupancy} />}
          {canSeeFinance && financials && <MobileFinancialsCard data={financials} />}
          {canSeeComplaints && (
            <>
              {complaintsQuery.isLoading && <SectionSkeleton className="h-32" />}
              {complaintsQuery.isError && <SectionError onRetry={() => complaintsQuery.refetch()} />}
              {complaintsQuery.isSuccess && <MobileIssuesCard issues={issues} highPriorityCount={highPriorityCount} />}
            </>
          )}
          {activitySources.length > 0 &&
            (activityFailed.length > 0 ? (
              <SectionError onRetry={() => activityFailed.forEach((query) => void query.refetch())} />
            ) : activityPending ? (
              <SectionSkeleton className="h-40" />
            ) : (
              <MobileActivityCard items={todayActivity} />
            ))}
        </div>
      </div>

      {/* Desktop */}
      <div className="hidden md:block">
        <DesktopHeader />
        <div className="flex flex-col gap-6 p-8">
          <div className={`grid grid-cols-1 items-stretch gap-6 ${canSeeFinance ? "lg:grid-cols-[2fr_1fr]" : ""}`}>
            {summaryQuery.isLoading && <SectionSkeleton className="h-48" />}
            {summaryQuery.isError && <SectionError onRetry={() => summaryQuery.refetch()} />}
            {occupancy && <OccupancyCard data={occupancy} />}
            {canSeeFinance && financials && <FinancialsCard data={financials} />}
          </div>
          <div className={`grid grid-cols-1 items-stretch gap-6 ${canSeeComplaints ? "lg:grid-cols-[2fr_1fr]" : ""}`}>
            {canSeeComplaints && (
              <>
                {complaintsQuery.isLoading && <SectionSkeleton className="h-48" />}
                {complaintsQuery.isError && <SectionError onRetry={() => complaintsQuery.refetch()} />}
                {complaintsQuery.isSuccess && <ActiveIssuesCard issues={issues} highPriorityCount={highPriorityCount} />}
              </>
            )}
            <TodaysActivity items={activity} />
          </div>
        </div>
      </div>
    </>
  );
}

export default function DashboardPage() {
  return (
    <RequirePermission permission="view_dashboard">
      <Suspense>
        <DashboardContent />
      </Suspense>
    </RequirePermission>
  );
}
