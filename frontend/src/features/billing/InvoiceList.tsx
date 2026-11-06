"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { FileText, FilterX, Plus, Search } from "lucide-react";
import { bulkIssueInvoices, type Invoice, type InvoiceFilters, listInvoicesFiltered } from "@/lib/api";
import { MoneyText } from "@/components/shared/MoneyText";
import { PermissionGate } from "@/components/shared/PermissionGate";
import { PropertyFilter, useActiveProperty } from "@/components/shared/PropertyFilter";
import { SectionError, SectionSkeleton } from "@/components/shared/SectionState";
import { StatusPill, getStatusTone } from "@/components/shared/StatusPill";
import { formatDate } from "@/lib/date";
import { queryKeys } from "@/lib/queryKeys";
import { afterInvoiceIssued } from "@/lib/refresh";
import { useSession } from "@/lib/session";
import { GenerateInvoiceDialog } from "./GenerateInvoiceDialog";
import { BulkGenerateDialog } from "./BulkGenerateDialog";

const STATUS_CHOICES = [
  "all",
  "needs_review",
  "scheduled",
  "outstanding",
  "overdue",
  "draft",
  "issued",
  "partially_paid",
  "paid",
] as const;

// Automatic-billing views map to ?review= rather than ?status= (both are drafts).
const REVIEW_CHOICES: Record<string, InvoiceFilters["review"]> = {
  needs_review: "needs_confirmation",
  scheduled: "scheduled",
};
// Lists whose draft rows can be selected and issued together.
const SELECTABLE_CHOICES = new Set(["needs_review", "scheduled", "draft"]);

/** The automatic-billing badge for a draft, if any. */
function autoBillingBadge(invoice: Invoice, t: ReturnType<typeof useTranslations>) {
  if (invoice.status !== "draft" || !invoice.auto_generated) return null;
  if (invoice.review_reasons.length > 0) return { label: t("badge.needsConfirmation"), tone: "warn" as const };
  if (invoice.auto_issue_held) return { label: t("badge.onHold"), tone: "neutral" as const };
  if (invoice.auto_issue_on) {
    return { label: t("badge.autoIssuesOn", { date: formatDate(invoice.auto_issue_on) }), tone: "accent" as const };
  }
  return null;
}

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
    case "needs_review":
      return t("filters.statusNeedsReview");
    case "scheduled":
      return t("filters.statusScheduled");
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
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [issueResult, setIssueResult] = useState<string | null>(null);
  const { can } = useSession();

  const review = REVIEW_CHOICES[status];
  const filters: InvoiceFilters = {
    property: propertyId ?? undefined,
    status: status === "all" || review ? undefined : status,
    review,
    period: period || undefined,
    search: search || undefined,
  };
  const selectable = SELECTABLE_CHOICES.has(status) && can("manage_invoices");

  const { data: invoices = [], isLoading, isError, refetch } = useQuery({
    queryKey: queryKeys.invoices.list(filters),
    queryFn: () => listInvoicesFiltered(filters),
  });

  const hasFilters = status !== "all" || period || search;
  const chosen = invoices.filter((invoice) => invoice.status === "draft" && selected.has(invoice.id)).map((i) => i.id);

  const issueMutation = useMutation({
    mutationFn: (ids: string[]) => bulkIssueInvoices(ids),
    onSuccess: async (result, ids) => {
      setSelected(new Set());
      setIssueResult(t("issueSelectedResult", { issued: result.issued, total: ids.length }));
      await afterInvoiceIssued({ propertyId: propertyId ?? undefined });
    },
  });

  function toggle(id: string) {
    setIssueResult(null);
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function changeStatus(value: string) {
    setStatus(value);
    setSelected(new Set());
    setIssueResult(null);
  }

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
          onChange={(event) => changeStatus(event.target.value)}
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
              changeStatus("all");
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

      {selectable && (chosen.length > 0 || issueResult) && (
        <div className="flex flex-wrap items-center gap-3">
          {chosen.length > 0 && (
            <button
              type="button"
              disabled={issueMutation.isPending}
              onClick={() => {
                if (window.confirm(t("issueSelectedConfirm", { count: chosen.length }))) issueMutation.mutate(chosen);
              }}
              className="rounded-xl bg-accent px-3 py-2 text-sm font-semibold text-ink-inverse transition-colors hover:bg-accent-hover disabled:opacity-50 cursor-pointer"
            >
              {t("issueSelected", { count: chosen.length })}
            </button>
          )}
          {issueResult && (
            <p role="status" className="text-sm text-ink-muted">
              {issueResult}
            </p>
          )}
        </div>
      )}

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
              const badge = autoBillingBadge(invoice, t);
              const row = (
                <Link
                  key={invoice.id}
                  href={`/billing/invoices/${invoice.id}`}
                  className="grid flex-1 grid-cols-1 gap-2 px-5 py-3.5 text-sm transition-colors hover:bg-surface-page md:grid-cols-12 md:items-center md:gap-4"
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
                  <div className="col-span-1 flex flex-wrap gap-1 md:justify-end">
                    <StatusPill label={tStatus(invoice.status)} tone={getStatusTone(invoice.status)} />
                    {badge && <StatusPill label={badge.label} tone={badge.tone} />}
                  </div>
                </Link>
              );
              if (!selectable || invoice.status !== "draft") return row;
              return (
                <div key={invoice.id} className="flex items-center">
                  <input
                    type="checkbox"
                    checked={selected.has(invoice.id)}
                    onChange={() => toggle(invoice.id)}
                    aria-label={t("selectRow", { name: invoice.resident_name })}
                    className="ml-5 size-4 shrink-0 accent-accent"
                  />
                  {row}
                </div>
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
