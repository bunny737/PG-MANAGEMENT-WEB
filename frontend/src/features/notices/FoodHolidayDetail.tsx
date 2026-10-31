"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { ArrowLeft, Lock } from "lucide-react";
import { MoneyText } from "@/components/shared/MoneyText";
import { SectionError, SectionSkeleton } from "@/components/shared/SectionState";
import { StatusPill, type Tone } from "@/components/shared/StatusPill";
import {
  ApiError,
  type Announcement,
  deleteFoodHoliday,
  type FoodHolidayCredit,
  type FoodHolidayCreditStatus,
  getFoodHoliday,
  getNotice,
  listFoodHolidayCredits,
  restoreFoodHolidayCredit,
} from "@/lib/api";
import { formatDate } from "@/lib/date";
import { compareMoney, ZERO } from "@/lib/money";
import { queryKeys } from "@/lib/queryKeys";
import { afterFoodHolidayChange } from "@/lib/refresh";
import { useSession } from "@/lib/session";
import { FoodHolidayFormSheet } from "./FoodHolidayFormSheet";
import { NoticeCard } from "./NoticeCard";
import { NoticeFormSheet } from "./NoticeFormSheet";

const STATUS_TONE: Record<FoodHolidayCreditStatus, Tone> = {
  estimated: "neutral",
  pending: "warn",
  invoiced: "accent",
  settled: "good",
  waived: "neutral",
};

function isPositive(value: string): boolean {
  return compareMoney(value, ZERO) === 1;
}

export function FoodHolidayDetail({ id }: { id: string }) {
  const t = useTranslations("notices");
  const tCredit = useTranslations("notices.credits");
  const router = useRouter();
  const { can } = useSession();
  const [editing, setEditing] = useState(false);
  const [editingNotice, setEditingNotice] = useState<Announcement | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const holidayQuery = useQuery({ queryKey: queryKeys.notices.holiday(id), queryFn: () => getFoodHoliday(id), retry: false });
  const holiday = holidayQuery.data;

  const noticeQuery = useQuery({
    queryKey: queryKeys.notices.detail(holiday?.announcement ?? ""),
    queryFn: () => getNotice(holiday?.announcement as string),
    enabled: !!holiday?.announcement,
  });

  // The credit rows are finance: never requested without view_finance.
  const canViewCredits = can("view_finance");
  const creditsQuery = useQuery({
    queryKey: queryKeys.notices.credits(id),
    queryFn: () => listFoodHolidayCredits(id),
    enabled: canViewCredits,
  });

  const restoreMutation = useMutation({
    mutationFn: (credit: FoodHolidayCredit) => restoreFoodHolidayCredit(id, credit.id as string),
    onSuccess: () => afterFoodHolidayChange(),
    onError: (err) => setActionError(err instanceof ApiError ? err.message : t("detail.errActionFailed")),
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteFoodHoliday(id),
    onSuccess: async () => {
      await afterFoodHolidayChange();
      router.push("/notices?tab=holidays");
    },
    onError: async (err) => {
      setActionError(err instanceof ApiError ? err.message : t("detail.errActionFailed"));
      // It may have been locked by an issued bill since this page loaded.
      if (err instanceof ApiError && err.status === 409) await afterFoodHolidayChange();
    },
  });

  if (holidayQuery.isLoading) return <SectionSkeleton className="h-96" />;
  if (holidayQuery.isError || !holiday) {
    const gone = holidayQuery.error instanceof ApiError && holidayQuery.error.status === 404;
    return (
      <div className="space-y-4">
        <BackLink label={t("detail.back")} />
        {gone ? (
          <p className="text-sm text-ink-muted">{t("detail.notFound")}</p>
        ) : (
          <SectionError onRetry={() => holidayQuery.refetch()} message={t("detail.errLoadFailed")} />
        )}
      </div>
    );
  }

  // A holiday that adjusts bills can't be changed or deleted without manage_invoices (the backend enforces
  // it against the locked row), so those actions aren't offered.
  const canChange = can("manage_notices") && (!holiday.adjust_in_bill || can("manage_invoices"));
  const canRestore = can("manage_notices") && can("manage_invoices") && holiday.adjust_in_bill;
  const credits = creditsQuery.data;

  function handleDelete() {
    setActionError(null);
    if (window.confirm(holiday?.announcement ? t("detail.deleteConfirmWithNotice") : t("detail.deleteConfirm"))) {
      deleteMutation.mutate();
    }
  }

  return (
    <div className="space-y-6">
      <BackLink label={t("detail.back")} />

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-bold text-ink">{holiday.name}</h1>
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
          <p className="text-sm text-ink-muted">
            {holiday.property_name} · {formatDate(holiday.start_date)} – {formatDate(holiday.end_date)} ·{" "}
            {t("holidays.days", { count: holiday.total_days })}
          </p>
          {holiday.adjust_in_bill && holiday.rate_per_day != null && (
            <p className="text-sm text-ink-muted">
              {t("detail.rate")}: <MoneyText value={holiday.rate_per_day} className="font-semibold text-ink" />
            </p>
          )}
        </div>
        {canChange && (
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setEditing(true)}
              className="rounded-xl border border-border bg-surface-card px-3 py-2 text-sm font-semibold text-ink transition-colors hover:bg-surface-page cursor-pointer"
            >
              {t("detail.edit")}
            </button>
            <button
              type="button"
              onClick={handleDelete}
              disabled={holiday.is_locked || deleteMutation.isPending}
              title={holiday.is_locked ? t("detail.deleteLocked") : undefined}
              className="rounded-xl border border-border bg-surface-card px-3 py-2 text-sm font-semibold text-status-critical transition-colors hover:bg-surface-page disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
            >
              {t("detail.delete")}
            </button>
          </div>
        )}
      </div>
      {holiday.is_locked && canChange && <p className="text-xs text-ink-muted">{t("detail.deleteLocked")}</p>}
      {actionError && (
        <p role="alert" className="text-sm text-status-critical">
          {actionError}
        </p>
      )}

      <section className="space-y-3">
        <h2 className="text-sm font-bold text-ink">{t("detail.noticeHeading")}</h2>
        {!holiday.announcement && <p className="text-sm text-ink-muted">{t("detail.noNotice")}</p>}
        {holiday.announcement && noticeQuery.isLoading && <SectionSkeleton className="h-28" />}
        {holiday.announcement && noticeQuery.isError && (
          <SectionError onRetry={() => noticeQuery.refetch()} message={t("notice.errLoadFailed")} />
        )}
        {noticeQuery.data && (
          <NoticeCard notice={noticeQuery.data} onEdit={setEditingNotice} hideHolidayLink />
        )}
      </section>

      {canViewCredits && (
        <section className="space-y-3">
          <h2 className="text-sm font-bold text-ink">{t("detail.creditsHeading")}</h2>
          {!holiday.adjust_in_bill && <p className="text-sm text-ink-muted">{t("detail.notAdjustedNote")}</p>}
          {holiday.adjust_in_bill && creditsQuery.isLoading && <SectionSkeleton className="h-40" />}
          {holiday.adjust_in_bill && creditsQuery.isError && (
            <SectionError onRetry={() => creditsQuery.refetch()} message={t("detail.errCreditsFailed")} />
          )}
          {holiday.adjust_in_bill && credits && (
            <>
              <dl className="grid grid-cols-2 gap-3 md:grid-cols-4">
                <Total
                  label={tCredit("totals.credited")}
                  value={credits.totals.credited}
                  note={tCredit("count", { count: credits.totals.credited_count })}
                />
                {credits.totals.estimated_count > 0 && (
                  <Total
                    label={tCredit("totals.estimated")}
                    value={credits.totals.estimated}
                    note={tCredit("count", { count: credits.totals.estimated_count })}
                  />
                )}
                {credits.totals.waived_count > 0 && (
                  <Total
                    label={tCredit("totals.waived")}
                    note={tCredit("count", { count: credits.totals.waived_count })}
                  />
                )}
                {isPositive(credits.totals.clawback) && (
                  <Total label={tCredit("totals.clawback")} value={credits.totals.clawback} />
                )}
              </dl>
              {credits.credits.length === 0 ? (
                <p className="text-sm text-ink-muted">{tCredit("empty")}</p>
              ) : (
                <div className="overflow-x-auto rounded-2xl border border-border bg-surface-card">
                  <table className="w-full text-left text-sm">
                    <thead className="border-b border-border bg-surface-page text-xs uppercase tracking-wider text-ink-muted">
                      <tr>
                        <th className="px-4 py-2 font-bold">{tCredit("columns.resident")}</th>
                        <th className="px-4 py-2 font-bold">{tCredit("columns.days")}</th>
                        <th className="px-4 py-2 font-bold">{tCredit("columns.rate")}</th>
                        <th className="px-4 py-2 font-bold">{tCredit("columns.amount")}</th>
                        <th className="px-4 py-2 font-bold">{tCredit("columns.status")}</th>
                        <th className="px-4 py-2 font-bold">{tCredit("columns.invoice")}</th>
                        <th className="px-4 py-2" />
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {credits.credits.map((credit) => (
                        <tr key={credit.id ?? `estimated-${credit.resident}`}>
                          <td className="px-4 py-2.5">
                            <Link href={`/residents/${credit.resident}`} className="font-semibold text-ink hover:text-accent">
                              {credit.resident_name}
                            </Link>
                          </td>
                          <td className="px-4 py-2.5 tabular-nums">{credit.days}</td>
                          <td className="px-4 py-2.5">
                            <MoneyText value={credit.rate} />
                          </td>
                          <td className="px-4 py-2.5">
                            <MoneyText value={credit.amount} className="font-semibold" />
                            {isPositive(credit.clawback_amount) && (
                              <p className="text-xs text-status-warn">
                                {tCredit("clawedBack")}: <MoneyText value={credit.clawback_amount} />
                              </p>
                            )}
                          </td>
                          <td className="px-4 py-2.5">
                            <StatusPill label={tCredit(`status.${credit.status}`)} tone={STATUS_TONE[credit.status]} />
                          </td>
                          <td className="px-4 py-2.5">
                            {credit.invoice ? (
                              <Link
                                href={`/billing/invoices/${credit.invoice}`}
                                className="text-xs font-semibold text-accent hover:text-accent-hover"
                              >
                                {tCredit("viewInvoice")}
                              </Link>
                            ) : (
                              <span className="text-ink-faint">—</span>
                            )}
                          </td>
                          <td className="px-4 py-2.5 text-right">
                            {credit.status === "waived" && canRestore && (
                              <button
                                type="button"
                                onClick={() => {
                                  setActionError(null);
                                  restoreMutation.mutate(credit);
                                }}
                                disabled={restoreMutation.isPending}
                                className="text-xs font-semibold text-accent hover:text-accent-hover disabled:opacity-60 cursor-pointer"
                              >
                                {tCredit("restore")}
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {credits.totals.estimated_count > 0 && (
                <p className="text-xs text-ink-muted">{tCredit("estimatedLegend")}</p>
              )}
            </>
          )}
        </section>
      )}

      {editing && <FoodHolidayFormSheet initial={holiday} defaultProperty={null} onClose={() => setEditing(false)} />}
      {editingNotice && (
        <NoticeFormSheet initial={editingNotice} defaultProperty={null} onClose={() => setEditingNotice(null)} />
      )}
    </div>
  );
}

function BackLink({ label }: { label: string }) {
  return (
    <Link
      href="/notices?tab=holidays"
      className="inline-flex items-center gap-1.5 text-sm font-medium text-ink-muted hover:text-ink"
    >
      <ArrowLeft className="size-4" />
      {label}
    </Link>
  );
}

function Total({ label, value, note }: { label: string; value?: string; note?: string }) {
  return (
    <div className="rounded-2xl border border-border bg-surface-card px-4 py-3">
      <dt className="text-xs text-ink-faint">{label}</dt>
      <dd className="mt-0.5">
        {value !== undefined && <MoneyText value={value} className="text-base font-bold text-ink" />}
        {note && <span className="block text-xs text-ink-muted">{note}</span>}
      </dd>
    </div>
  );
}
