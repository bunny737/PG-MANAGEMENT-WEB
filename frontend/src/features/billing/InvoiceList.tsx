"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { FileText, FilterX, Plus, Search } from "lucide-react";
import { type Invoice, type InvoiceFilters, listInvoicesFiltered } from "@/lib/api";
import { MoneyText } from "@/components/shared/MoneyText";
import { PermissionGate } from "@/components/shared/PermissionGate";
import { PropertyFilter, useActiveProperty } from "@/components/shared/PropertyFilter";
import { SectionError, SectionSkeleton } from "@/components/shared/SectionState";
import { StatusPill, getStatusTone } from "@/components/shared/StatusPill";
import { queryKeys } from "@/lib/queryKeys";
import { GenerateInvoiceDialog } from "./GenerateInvoiceDialog";
import { BulkGenerateDialog } from "./BulkGenerateDialog";

const STATUS_CHOICES = ["all", "outstanding", "overdue", "draft", "issued", "partially_paid", "paid"] as const;

function dueLabel(invoice: Invoice, t: ReturnType<typeof useTranslations>): { label: string; critical: boolean } {
  if (invoice.status === "paid") return { label: "", critical: false };
  const due = new Date(invoice.due_date);
  const today = new Date();
  due.setHours(0, 0, 0, 0);
  today.setHours(0, 0, 0, 0);
  const days = Math.round((due.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));
  if (days < 0) return { label: t("overdueByDays", { days: Math.abs(days) }), critical: true };
  if (days === 0) return { label: t("dueToday"), critical: false };
  return { label: t("dueInDays", { days }), critical: false };
}

function statusChoiceLabel(
  choice: (typeof STATUS_CHOICES)[number],
  t: ReturnType<typeof useTranslations>,
  tStatus: ReturnType<typeof useTranslations>
): string {
  switch (choice) {
    case "all":
      return t("filters.statusAll");
    case "outstanding":
      return t("filters.statusOutstanding");
    case "overdue":
      return t("filters.statusOverdue");
    default:
      return tStatus(choice);
  }
}

export function InvoiceList() {
  const t = useTranslations("billing.invoices");
  const tStatus = useTranslations("status");
  const router = useRouter();
  const searchParams = useSearchParams();
  const { propertyId } = useActiveProperty();

  const [status, setStatus] = useState(searchParams.get("status") ?? "all");
  const [period, setPeriod] = useState(searchParams.get("period") ?? "");
  const [search, setSearch] = useState(searchParams.get("search") ?? "");
  const [showGenerate, setShowGenerate] = useState(false);
  const [showBulkGenerate, setShowBulkGenerate] = useState(false);

  const filters: InvoiceFilters = {
    property: propertyId ?? undefined,
    status: status === "all" ? undefined : status,
    period: period || undefined,
    search: search || undefined,
  };

  const { data: invoices = [], isLoading, isError, refetch } = useQuery({
    queryKey: queryKeys.invoices.list(filters),
    queryFn: () => listInvoicesFiltered(filters),
  });

  const hasFilters = status !== "all" || period || search;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold text-ink">{t("title")}</h2>
          <p className="text-sm text-ink-muted">{t("subtitle")}</p>
        </div>
        <PermissionGate permission="manage_invoices">
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setShowBulkGenerate(true)}
              className="rounded-xl border border-border bg-surface-card px-3 py-2 text-sm font-semibold text-ink transition-colors hover:bg-surface-subtle cursor-pointer"
            >
              {t("bulkGenerate")}
            </button>
            <button
              type="button"
              onClick={() => setShowGenerate(true)}
              className="inline-flex items-center gap-1.5 rounded-xl bg-accent px-3 py-2 text-sm font-semibold text-ink-inverse transition-colors hover:bg-accent-hover cursor-pointer"
            >
              <Plus className="size-4" />
              {t("generate")}
            </button>
          </div>
        </PermissionGate>
      </div>

      <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-border bg-surface-card p-4">
        <PropertyFilter />
        <select
          value={status}
          onChange={(event) => setStatus(event.target.value)}
          className="rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
        >
          {STATUS_CHOICES.map((choice) => (
            <option key={choice} value={choice}>
              {statusChoiceLabel(choice, t, tStatus)}
            </option>
          ))}
        </select>
        <input
          type="month"
          value={period}
          onChange={(event) => setPeriod(event.target.value)}
          className="rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
        />
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
        {hasFilters && (
          <button
            type="button"
            onClick={() => {
              setStatus("all");
              setPeriod("");
              setSearch("");
            }}
            className="rounded-xl border border-border bg-surface-page p-2 text-ink-muted transition-colors hover:text-status-critical cursor-pointer"
            title={t("filters.clear")}
          >
            <FilterX className="size-4" />
          </button>
        )}
      </div>

      {isLoading && <SectionSkeleton className="h-64" />}
      {isError && <SectionError onRetry={() => refetch()} message={t("errLoadFailed")} />}

      {!isLoading && !isError && invoices.length === 0 && (
        <div className="flex flex-col items-center gap-2 rounded-2xl border border-border bg-surface-card p-12 text-center">
          <FileText className="size-8 text-ink-faint" />
          <h3 className="text-sm font-bold text-ink">{t("emptyTitle")}</h3>
          <p className="text-xs text-ink-muted">{t("emptyDesc")}</p>
        </div>
      )}

      {!isLoading && !isError && invoices.length > 0 && (
        <div className="overflow-hidden rounded-2xl border border-border bg-surface-card">
          <div className="hidden grid-cols-12 gap-4 border-b border-border bg-surface-page px-5 py-3 text-xs font-bold uppercase tracking-wider text-ink-muted md:grid">
            <div className="col-span-3">{t("table.resident")}</div>
            <div className="col-span-2">{t("table.roomBed")}</div>
            <div className="col-span-2">{t("table.period")}</div>
            <div className="col-span-2 text-right">{t("table.amount")}</div>
            <div className="col-span-2">{t("table.due")}</div>
            <div className="col-span-1 text-right">{t("table.status")}</div>
          </div>
          <div className="divide-y divide-border">
            {invoices.map((invoice) => {
              const due = dueLabel(invoice, t);
              return (
                <Link
                  key={invoice.id}
                  href={`/billing/invoices/${invoice.id}`}
                  className="grid grid-cols-1 gap-2 px-5 py-3.5 text-sm transition-colors hover:bg-surface-page md:grid-cols-12 md:items-center md:gap-4"
                >
                  <div className="col-span-3 font-semibold text-ink">{invoice.resident_name}</div>
                  <div className="col-span-2 text-ink-muted">
                    {invoice.room_number ? `${invoice.room_number} / ${invoice.bed_number}` : "—"}
                  </div>
                  <div className="col-span-2 text-ink-muted">{invoice.period_start.slice(0, 7)}</div>
                  <div className="col-span-2 text-right tabular-nums">
                    <MoneyText value={invoice.amount_paid} /> / <MoneyText value={invoice.total} />
                  </div>
                  <div className={due.critical ? "col-span-2 text-status-critical" : "col-span-2 text-ink-muted"}>
                    {due.label}
                  </div>
                  <div className="col-span-1 flex md:justify-end">
                    <StatusPill label={tStatus(invoice.status)} tone={getStatusTone(invoice.status)} />
                  </div>
                </Link>
              );
            })}
          </div>
        </div>
      )}

      {showGenerate && (
        <GenerateInvoiceDialog
          onClose={() => setShowGenerate(false)}
          onCreated={(invoice) => {
            setShowGenerate(false);
            router.push(`/billing/invoices/${invoice.id}`);
          }}
        />
      )}
      {showBulkGenerate && <BulkGenerateDialog onClose={() => setShowBulkGenerate(false)} />}
    </div>
  );
}
