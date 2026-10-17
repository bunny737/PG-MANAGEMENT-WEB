"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { Receipt, Search, Trash2 } from "lucide-react";
import { deletePayment, listPaymentsFiltered, type Payment, type PaymentFilters, type PaymentMode } from "@/lib/api";
import { MoneyText } from "@/components/shared/MoneyText";
import { PermissionGate } from "@/components/shared/PermissionGate";
import { PropertyFilter, useActiveProperty } from "@/components/shared/PropertyFilter";
import { SectionError, SectionSkeleton } from "@/components/shared/SectionState";
import { queryKeys } from "@/lib/queryKeys";
import { afterPayment } from "@/lib/refresh";
import { currentMonthKey } from "@/lib/period";

const MODES: PaymentMode[] = ["cash", "upi", "bank_transfer", "card", "cheque"];

export function PaymentsList() {
  const t = useTranslations("billing.payments");
  const tStatus = useTranslations("status");
  const { propertyId } = useActiveProperty();
  const queryClient = useQueryClient();

  const [month, setMonth] = useState(currentMonthKey());
  const [mode, setMode] = useState("");
  const [search, setSearch] = useState("");

  const filters: PaymentFilters = {
    property: propertyId ?? undefined,
    month: month || undefined,
    payment_mode: mode || undefined,
    search: search || undefined,
  };

  const { data: payments = [], isLoading, isError, refetch } = useQuery({
    queryKey: queryKeys.payments.list(filters),
    queryFn: () => listPaymentsFiltered(filters),
  });

  const deleteMutation = useMutation({
    mutationFn: (payment: Payment) => deletePayment(payment.id),
    onSuccess: async (_void, payment) => {
      await afterPayment({ invoiceId: payment.invoice, residentId: payment.resident, propertyId: payment.property });
      queryClient.removeQueries({ queryKey: queryKeys.payments.detail(payment.id) });
    },
  });

  function handleDelete(payment: Payment) {
    if (window.confirm(t("deleteConfirmBody"))) deleteMutation.mutate(payment);
  }

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
        <select
          value={mode}
          onChange={(event) => setMode(event.target.value)}
          className="rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
        >
          <option value="">{t("filters.allModes")}</option>
          {MODES.map((m) => (
            <option key={m} value={m}>
              {tStatus(m)}
            </option>
          ))}
        </select>
        <div className="relative min-w-[12rem] flex-1">
          <Search className="absolute inset-y-0 left-3 my-auto size-4 text-ink-faint" />
          <input
            type="text"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t("filters.search")}
            className="w-full rounded-xl border border-border bg-surface-card py-2 pl-9 pr-3 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
          />
        </div>
      </div>

      {isLoading && <SectionSkeleton className="h-64" />}
      {isError && <SectionError onRetry={() => refetch()} message={t("errLoadFailed")} />}

      {!isLoading && !isError && payments.length === 0 && (
        <div className="flex flex-col items-center gap-2 rounded-2xl border border-border bg-surface-card p-12 text-center">
          <Receipt className="size-8 text-ink-faint" />
          <h3 className="text-sm font-bold text-ink">{t("emptyTitle")}</h3>
          <p className="text-xs text-ink-muted">{t("emptyDesc")}</p>
        </div>
      )}

      {!isLoading && !isError && payments.length > 0 && (
        <div className="overflow-hidden rounded-2xl border border-border bg-surface-card">
          <div className="hidden grid-cols-12 gap-4 border-b border-border bg-surface-page px-5 py-3 text-xs font-bold uppercase tracking-wider text-ink-muted md:grid">
            <div className="col-span-3">{t("table.resident")}</div>
            <div className="col-span-2">{t("table.period")}</div>
            <div className="col-span-2 text-right">{t("table.amount")}</div>
            <div className="col-span-2">{t("table.mode")}</div>
            <div className="col-span-2">{t("table.receipt")}</div>
            <div className="col-span-1 text-right">{t("table.date")}</div>
          </div>
          <div className="divide-y divide-border">
            {payments.map((payment) => (
              <div key={payment.id} className="grid grid-cols-1 gap-2 px-5 py-3.5 text-sm md:grid-cols-12 md:items-center md:gap-4">
                <Link href={`/billing/payments/${payment.id}`} className="col-span-3 font-semibold text-ink hover:text-accent">
                  {payment.resident_name}
                </Link>
                <div className="col-span-2 text-ink-muted">{payment.invoice_period_start.slice(0, 7)}</div>
                <div className="col-span-2 text-right">
                  <MoneyText value={payment.amount} />
                </div>
                <div className="col-span-2 text-ink-muted">{tStatus(payment.payment_mode)}</div>
                <div className="col-span-2 text-ink-muted">{payment.receipt_number ?? "—"}</div>
                <div className="col-span-1 flex items-center justify-end gap-2">
                  <span className="text-ink-muted">{payment.payment_date}</span>
                  <PermissionGate permission="manage_payments">
                    <button
                      type="button"
                      onClick={() => handleDelete(payment)}
                      className="text-ink-faint hover:text-status-critical cursor-pointer"
                      title={t("delete")}
                    >
                      <Trash2 className="size-3.5" />
                    </button>
                  </PermissionGate>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
