"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Dialog } from "@/components/ui/Dialog";
import { MoneyText } from "@/components/shared/MoneyText";
import { ApiError, createPayment, downloadReceiptPdf, type Invoice, type Payment, type PaymentMode } from "@/lib/api";
import { triggerDownload } from "@/lib/download";
import { createIdempotencyKey } from "@/lib/idempotency";
import { isAtMost } from "@/lib/money";
import { afterPayment } from "@/lib/refresh";

const MODES: PaymentMode[] = ["cash", "upi", "bank_transfer", "card", "cheque"];

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

interface RecordPaymentDialogProps {
  invoice: Invoice;
  onClose: () => void;
  /** Fired once after a successful record (201 or a 200 replay). */
  onRecorded?: (payment: Payment) => void;
}

export function RecordPaymentDialog({ invoice, onClose, onRecorded }: RecordPaymentDialogProps) {
  const t = useTranslations("billing.recordPayment");
  const tStatus = useTranslations("status");
  const [idempotencyKey] = useState(createIdempotencyKey);
  const [amountMode, setAmountMode] = useState<"full" | "custom">("full");
  const [customAmount, setCustomAmount] = useState(invoice.balance_due);
  const [mode, setMode] = useState<PaymentMode>("cash");
  const [date, setDate] = useState(todayISO());
  const [reference, setReference] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [recorded, setRecorded] = useState<{ payment: Payment; replayed: boolean } | null>(null);

  const amount = amountMode === "full" ? invoice.balance_due : customAmount;
  const amountValid = amount.trim() !== "" && isAtMost(amount, invoice.balance_due);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!amountValid) {
      setError(t("errExceedsBalance"));
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      const { payment, replayed } = await createPayment(
        { invoice: invoice.id, amount, payment_date: date, payment_mode: mode, reference: reference || undefined },
        idempotencyKey
      );
      await afterPayment({ invoiceId: invoice.id, residentId: invoice.resident, propertyId: invoice.property });
      setRecorded({ payment, replayed });
      onRecorded?.(payment);
    } catch (err) {
      if (err instanceof ApiError) {
        // Validation errors (overpayment, invoice already paid, ...) carry
        // their own friendly message on the `amount` field — only
        // IDEMPOTENCY_KEY_REUSED is a top-level `code` (a 409 Conflict;
        // field-level ValidationError codes don't survive to JSON).
        const code = (err.body as { code?: string }).code;
        const fieldMessage = err.fieldError("amount");
        if (fieldMessage) setError(fieldMessage);
        else if (code === "IDEMPOTENCY_KEY_REUSED") setError(t("errReused"));
        else setError(err.message);
      } else {
        setError(String(err));
      }
    } finally {
      setSubmitting(false);
    }
  }

  const modeLabels = useMemo(
    () => Object.fromEntries(MODES.map((m) => [m, tStatus(m)])),
    [tStatus]
  );

  if (recorded) {
    return (
      <Dialog open onClose={onClose} title={t("title")}>
        <div className="space-y-4">
          <p className="text-sm text-ink">{recorded.replayed ? t("replayed") : t("success")}</p>
          <div className="rounded-xl border border-border bg-surface-page p-3 text-sm">
            <MoneyText value={recorded.payment.amount} className="text-base font-bold text-ink" />
            {recorded.payment.receipt_number && (
              <p className="mt-1 text-xs text-ink-muted">{recorded.payment.receipt_number}</p>
            )}
          </div>
          <div className="flex gap-2">
            <a
              href={`/billing/payments/${recorded.payment.id}`}
              className="flex-1 rounded-xl border border-border bg-surface-card py-2 text-center text-sm font-semibold text-ink transition-colors hover:bg-surface-subtle"
            >
              {t("viewReceipt")}
            </a>
            <button
              type="button"
              onClick={() => downloadReceiptPdf(recorded.payment.id).then(triggerDownload)}
              className="flex-1 rounded-xl border border-border bg-surface-card py-2 text-sm font-semibold text-ink transition-colors hover:bg-surface-subtle cursor-pointer"
            >
              {t("downloadPdf")}
            </button>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="w-full rounded-xl bg-accent py-2.5 text-sm font-semibold text-ink-inverse transition-colors hover:bg-accent-hover cursor-pointer"
          >
            {t("close")}
          </button>
        </div>
      </Dialog>
    );
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title={t("title")}
      subtitle={t("subtitle", { resident: invoice.resident_name, period: invoice.period_start.slice(0, 7) })}
    >
      <div className="mb-4 grid grid-cols-3 gap-2 rounded-xl border border-border bg-surface-page p-3 text-center text-xs">
        <div>
          <p className="text-ink-faint">{t("total")}</p>
          <MoneyText value={invoice.total} className="font-bold text-ink" />
        </div>
        <div>
          <p className="text-ink-faint">{t("paidSoFar")}</p>
          <MoneyText value={invoice.amount_paid} className="font-bold text-ink" />
        </div>
        <div>
          <p className="text-ink-faint">{t("balance")}</p>
          <MoneyText value={invoice.balance_due} className="font-bold text-status-critical" />
        </div>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-1.5">
          <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">{t("amount")}</label>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setAmountMode("full")}
              className={`rounded-xl px-3 py-1.5 text-xs font-semibold transition-colors cursor-pointer ${amountMode === "full" ? "bg-accent text-ink-inverse" : "border border-border bg-surface-card text-ink-muted"}`}
            >
              {t("full")}
            </button>
            <button
              type="button"
              onClick={() => setAmountMode("custom")}
              className={`rounded-xl px-3 py-1.5 text-xs font-semibold transition-colors cursor-pointer ${amountMode === "custom" ? "bg-accent text-ink-inverse" : "border border-border bg-surface-card text-ink-muted"}`}
            >
              {t("custom")}
            </button>
          </div>
          <input
            type="text"
            inputMode="decimal"
            value={amount}
            disabled={amountMode === "full"}
            onChange={(event) => setCustomAmount(event.target.value)}
            className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15 disabled:bg-surface-page"
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">{t("mode")}</label>
            <select
              value={mode}
              onChange={(event) => setMode(event.target.value as PaymentMode)}
              className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
            >
              {MODES.map((m) => (
                <option key={m} value={m}>
                  {modeLabels[m]}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">{t("date")}</label>
            <input
              type="date"
              value={date}
              onChange={(event) => setDate(event.target.value)}
              max={todayISO()}
              className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
            />
          </div>
        </div>
        <div className="space-y-1.5">
          <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">{t("reference")}</label>
          <input
            type="text"
            value={reference}
            onChange={(event) => setReference(event.target.value)}
            className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
          />
        </div>
        {error && <p className="text-sm text-status-critical">{error}</p>}
        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded-xl bg-accent py-2.5 text-sm font-semibold text-ink-inverse transition-colors hover:bg-accent-hover disabled:opacity-60 cursor-pointer"
        >
          {submitting ? t("submitting") : t("submit")}
        </button>
      </form>
    </Dialog>
  );
}
