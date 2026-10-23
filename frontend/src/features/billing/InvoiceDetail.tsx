"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { ArrowLeft, Pencil, Plus, Trash2 } from "lucide-react";
import {
  addInvoiceLineItem,
  deleteInvoiceDraft,
  deleteInvoiceLineItem,
  getInvoice,
  type InvoiceLineItem,
  issueInvoice,
  listPaymentsFiltered,
  type LineType,
  updateInvoiceDraft,
  updateInvoiceLineItem,
} from "@/lib/api";
import { MoneyText } from "@/components/shared/MoneyText";
import { PermissionGate } from "@/components/shared/PermissionGate";
import { SectionError, SectionSkeleton } from "@/components/shared/SectionState";
import { StatusPill, getStatusTone } from "@/components/shared/StatusPill";
import { queryKeys } from "@/lib/queryKeys";
import { afterInvoiceChange, afterInvoiceIssued } from "@/lib/refresh";
import { AddLineItemDialog } from "./AddLineItemDialog";
import { RecordPaymentDialog } from "./RecordPaymentDialog";

export function InvoiceDetail({ id }: { id: string }) {
  const t = useTranslations("billing.detail");
  const tAddLine = useTranslations("billing.addLineDialog");
  const tStatus = useTranslations("status");
  const tLineType = useTranslations("billing.lineType");
  const router = useRouter();
  const queryClient = useQueryClient();

  const { data: invoice, isLoading, isError, refetch } = useQuery({
    queryKey: queryKeys.invoices.detail(id),
    queryFn: () => getInvoice(id),
  });

  const { data: payments = [] } = useQuery({
    queryKey: queryKeys.payments.list({ invoice: id }),
    queryFn: () => listPaymentsFiltered({ invoice: id }),
    enabled: !!invoice,
  });

  const [editingLine, setEditingLine] = useState<InvoiceLineItem | "new" | null>(null);
  const [showRecordPayment, setShowRecordPayment] = useState(false);
  const [dueDate, setDueDate] = useState<string | null>(null);

  const invalidateDetail = () => queryClient.invalidateQueries({ queryKey: queryKeys.invoices.detail(id) });

  const issueMutation = useMutation({
    mutationFn: () => issueInvoice(id),
    onSuccess: async (updated) => {
      await afterInvoiceIssued({ invoiceId: id, residentId: updated.resident, propertyId: updated.property });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteInvoiceDraft(id),
    onSuccess: async () => {
      if (invoice) await afterInvoiceChange({ residentId: invoice.resident, propertyId: invoice.property });
      router.push("/billing");
    },
  });

  const saveDueDateMutation = useMutation({
    mutationFn: (value: string) => updateInvoiceDraft(id, { due_date: value }),
    onSuccess: async () => {
      await invalidateDetail();
      setDueDate(null);
    },
  });

  async function handleAddOrEditLine(values: { line_type: LineType; label: string; amount: string }) {
    if (editingLine === "new") {
      await addInvoiceLineItem(id, values);
    } else if (editingLine) {
      await updateInvoiceLineItem(id, editingLine.id, values);
    }
    await invalidateDetail();
  }

  async function handleRemoveLine(line: InvoiceLineItem) {
    if (!window.confirm(tAddLine("removeConfirm"))) return;
    await deleteInvoiceLineItem(id, line.id);
    await invalidateDetail();
  }

  if (isLoading) return <SectionSkeleton className="h-96" />;
  if (isError || !invoice) return <SectionError onRetry={() => refetch()} message={t("errLoadFailed")} />;

  const isDraft = invoice.status === "draft";

  return (
    <div className="space-y-6">
      <Link href="/billing" className="inline-flex items-center gap-1.5 text-sm font-medium text-ink-muted hover:text-ink">
        <ArrowLeft className="size-4" />
        {t("back")}
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-ink">{invoice.resident_name}</h1>
          <p className="text-sm text-ink-muted">
            {invoice.room_number ? `${invoice.room_number} / ${invoice.bed_number} · ` : ""}
            {t("period")}: {invoice.period_start} – {invoice.period_end}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <StatusPill label={tStatus(invoice.status)} tone={getStatusTone(invoice.status)} />
          {invoice.is_overdue && <StatusPill label={t("overdueBadge")} tone="critical" />}
        </div>
      </div>

      <div className="rounded-2xl border border-border bg-surface-card p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-bold text-ink">{t("lineItems")}</h2>
          {isDraft && (
            <PermissionGate permission="manage_invoices">
              <button
                type="button"
                onClick={() => setEditingLine("new")}
                className="inline-flex items-center gap-1 text-xs font-semibold text-accent hover:text-accent-hover cursor-pointer"
              >
                <Plus className="size-3.5" />
                {t("addLine")}
              </button>
            </PermissionGate>
          )}
        </div>
        <div className="divide-y divide-border">
          {invoice.line_items.map((line) => (
            <div key={line.id} className="flex items-center justify-between py-2 text-sm">
              <div>
                <p className="font-medium text-ink">{line.label}</p>
                <p className="text-xs text-ink-muted">{tLineType(line.line_type)}</p>
              </div>
              <div className="flex items-center gap-3">
                <MoneyText value={line.amount} className="font-semibold" />
                {isDraft && (
                  <PermissionGate permission="manage_invoices">
                    <button
                      type="button"
                      onClick={() => setEditingLine(line)}
                      className="text-ink-faint hover:text-ink cursor-pointer"
                    >
                      <Pencil className="size-3.5" />
                    </button>
                    <button
                      type="button"
                      onClick={() => handleRemoveLine(line)}
                      className="text-ink-faint hover:text-status-critical cursor-pointer"
                    >
                      <Trash2 className="size-3.5" />
                    </button>
                  </PermissionGate>
                )}
              </div>
            </div>
          ))}
        </div>
        <div className="mt-3 space-y-1 border-t border-border pt-3 text-sm">
          <div className="flex justify-between">
            <span className="text-ink-muted">{t("total")}</span>
            <MoneyText value={invoice.total} className="font-bold" />
          </div>
          <div className="flex justify-between">
            <span className="text-ink-muted">{t("paid")}</span>
            <MoneyText value={invoice.amount_paid} />
          </div>
          <div className="flex justify-between text-base">
            <span className="font-bold text-ink">{t("balance")}</span>
            <MoneyText value={invoice.balance_due} attention className="font-bold" />
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        {Number(invoice.balance_due) > 0 && (
          <PermissionGate permission="manage_payments">
            <button
              type="button"
              onClick={() => setShowRecordPayment(true)}
              className="rounded-xl bg-accent px-4 py-2 text-sm font-semibold text-ink-inverse transition-colors hover:bg-accent-hover cursor-pointer"
            >
              {t("recordPayment")}
            </button>
          </PermissionGate>
        )}
        {isDraft && (
          <PermissionGate permission="manage_invoices">
            <button
              type="button"
              onClick={() => {
                if (window.confirm(t("issueConfirmBody"))) issueMutation.mutate();
              }}
              className="rounded-xl border border-border bg-surface-card px-4 py-2 text-sm font-semibold text-ink transition-colors hover:bg-surface-subtle cursor-pointer"
            >
              {t("issue")}
            </button>
            <button
              type="button"
              onClick={() => {
                if (window.confirm(t("deleteConfirmBody"))) deleteMutation.mutate();
              }}
              className="rounded-xl border border-border bg-surface-card px-4 py-2 text-sm font-semibold text-status-critical transition-colors hover:bg-status-critical-soft cursor-pointer"
            >
              {t("deleteDraft")}
            </button>
          </PermissionGate>
        )}
      </div>

      {isDraft && (
        <div className="rounded-2xl border border-border bg-surface-card p-5">
          <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">{t("dueDate")}</label>
          <div className="mt-1.5 flex items-center gap-2">
            <input
              type="date"
              value={dueDate ?? invoice.due_date}
              onChange={(event) => setDueDate(event.target.value)}
              className="rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
            />
            {dueDate && dueDate !== invoice.due_date && (
              <button
                type="button"
                onClick={() => saveDueDateMutation.mutate(dueDate)}
                className="rounded-xl bg-accent px-3 py-2 text-sm font-semibold text-ink-inverse cursor-pointer"
              >
                {t("saveDueDate")}
              </button>
            )}
          </div>
        </div>
      )}

      <div className="rounded-2xl border border-border bg-surface-card p-5">
        <h2 className="mb-3 text-sm font-bold text-ink">{t("payments")}</h2>
        {payments.length === 0 ? (
          <p className="text-sm text-ink-muted">{t("noPayments")}</p>
        ) : (
          <div className="divide-y divide-border">
            {payments.map((payment) => (
              <Link
                key={payment.id}
                href={`/billing/payments/${payment.id}`}
                className="flex items-center justify-between py-2 text-sm transition-colors hover:text-accent"
              >
                <div>
                  <p className="font-medium text-ink">{payment.payment_date}</p>
                  <p className="text-xs text-ink-muted">{payment.receipt_number ?? "—"}</p>
                </div>
                <MoneyText value={payment.amount} className="font-semibold" />
              </Link>
            ))}
          </div>
        )}
      </div>

      {editingLine && (
        <AddLineItemDialog
          initial={editingLine === "new" ? undefined : editingLine}
          onClose={() => setEditingLine(null)}
          onSubmit={handleAddOrEditLine}
        />
      )}
      {showRecordPayment && (
        <RecordPaymentDialog invoice={invoice} onClose={() => setShowRecordPayment(false)} />
      )}
    </div>
  );
}
