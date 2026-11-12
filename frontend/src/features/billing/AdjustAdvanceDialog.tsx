"use client";

import { useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { Dialog } from "@/components/ui/Dialog";
import { MoneyText } from "@/components/shared/MoneyText";
import {
  ApiError,
  adjustInvoiceAdvance,
  downloadReceiptPdf,
  type Invoice,
  type Payment,
} from "@/lib/api";
import { localDateKey } from "@/lib/date";
import { triggerDownload } from "@/lib/download";
import { createIdempotencyKey } from "@/lib/idempotency";
import { compareMoney, isMoneyInput, ZERO } from "@/lib/money";
import { afterPayment } from "@/lib/refresh";

interface AdjustAdvanceDialogProps {
  invoice: Invoice;
  heldAdvance: string;
  onClose: () => void;
  /** Fired once after a successful adjustment (201 or a 200 replay). */
  onAdjusted?: (payment: Payment) => void;
}

export function AdjustAdvanceDialog({
  invoice,
  heldAdvance,
  onClose,
  onAdjusted,
}: AdjustAdvanceDialogProps) {
  const t = useTranslations("billing.adjustAdvance");
  const balanceVsHeld = compareMoney(invoice.balance_due, heldAdvance);
  const maxAdjustable = balanceVsHeld === null || balanceVsHeld > 0 ? heldAdvance : invoice.balance_due;

  const [idempotencyKey] = useState(createIdempotencyKey);
  const [amountMode, setAmountMode] = useState<"full" | "custom">("full");
  const [customAmount, setCustomAmount] = useState(maxAdjustable);
  const [adjustmentDate, setAdjustmentDate] = useState(() => localDateKey(new Date()));
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [recorded, setRecorded] = useState<{ payment: Payment; replayed: boolean } | null>(null);

  const amount = amountMode === "full" ? maxAdjustable : customAmount;

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const trimmed = amount.trim();
    if (!trimmed || !isMoneyInput(trimmed) || compareMoney(trimmed, ZERO) !== 1) {
      setError(t("errInvalidAmount"));
      return;
    }
    if (compareMoney(trimmed, heldAdvance) === 1) {
      setError(t("errExceedsHeld"));
      return;
    }
    if (compareMoney(trimmed, invoice.balance_due) === 1) {
      setError(t("errExceedsBalance"));
      return;
    }

    setError(null);
    setSubmitting(true);
    try {
      const { payment, replayed } = await adjustInvoiceAdvance(
        invoice.id,
        {
          amount: trimmed,
          adjustment_date: adjustmentDate || undefined,
          note: note.trim() || undefined,
        },
        idempotencyKey
      );
      await afterPayment({
        invoiceId: invoice.id,
        residentId: invoice.resident,
        propertyId: invoice.property,
      });
      setRecorded({ payment, replayed });
      onAdjusted?.(payment);
    } catch (err) {
      if (err instanceof ApiError) {
        const code = (err.body as { code?: string }).code;
        const amountErr = err.fieldError("amount");
        const invoiceErr = err.fieldError("invoice");
        if (amountErr) setError(amountErr);
        else if (invoiceErr) setError(invoiceErr);
        else if (code === "FIRST_INVOICE_NOT_ISSUED") setError(t("errFirstInvoiceNotIssued"));
        else if (code === "IDEMPOTENCY_KEY_REUSED") setError(t("errReused"));
        else setError(err.message);
      } else {
        setError(String(err));
      }
    } finally {
      setSubmitting(false);
    }
  }

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
            <Link
              href={`/billing/payments/${recorded.payment.id}`}
              className="flex-1 rounded-xl border border-border bg-surface-card py-2 text-center text-sm font-semibold text-ink transition-colors hover:bg-surface-subtle"
            >
              {t("viewReceipt")}
            </Link>
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
      subtitle={t("subtitle", {
        resident: invoice.resident_name,
        period: invoice.period_start.slice(0, 7),
      })}
    >
      <div className="mb-4 grid grid-cols-3 gap-2 rounded-xl border border-border bg-surface-page p-3 text-center text-xs">
        <div>
          <p className="text-ink-faint">{t("heldAdvance")}</p>
          <MoneyText value={heldAdvance} className="font-bold text-ink" />
        </div>
        <div>
          <p className="text-ink-faint">{t("balance")}</p>
          <MoneyText value={invoice.balance_due} className="font-bold text-ink" />
        </div>
        <div>
          <p className="text-ink-faint">{t("maxAdjustable")}</p>
          <MoneyText value={maxAdjustable} className="font-bold text-accent" />
        </div>
      </div>

      <p
        role="note"
        className="rounded-xl border border-accent/25 bg-accent-soft/40 px-3 py-2 text-xs text-ink-muted"
      >
        {t("nonCashNotice")}
      </p>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-1.5">
          <label
            htmlFor="adjust-advance-amount"
            className="text-xs font-semibold uppercase tracking-wider text-ink-muted"
          >
            {t("amount")}
          </label>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setAmountMode("full")}
              className={`rounded-xl px-3 py-1.5 text-xs font-semibold transition-colors cursor-pointer ${
                amountMode === "full"
                  ? "bg-accent text-ink-inverse"
                  : "border border-border bg-surface-card text-ink-muted"
              }`}
            >
              {t("full")}
            </button>
            <button
              type="button"
              onClick={() => setAmountMode("custom")}
              className={`rounded-xl px-3 py-1.5 text-xs font-semibold transition-colors cursor-pointer ${
                amountMode === "custom"
                  ? "bg-accent text-ink-inverse"
                  : "border border-border bg-surface-card text-ink-muted"
              }`}
            >
              {t("custom")}
            </button>
          </div>
          <input
            id="adjust-advance-amount"
            type="text"
            inputMode="decimal"
            value={amount}
            disabled={amountMode === "full"}
            onChange={(event) => setCustomAmount(event.target.value)}
            className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15 disabled:bg-surface-page"
          />
        </div>

        <div className="space-y-1.5">
          <label
            htmlFor="adjust-advance-date"
            className="text-xs font-semibold uppercase tracking-wider text-ink-muted"
          >
            {t("date")}
          </label>
          <input
            id="adjust-advance-date"
            type="date"
            value={adjustmentDate}
            max={localDateKey(new Date())}
            onChange={(event) => setAdjustmentDate(event.target.value)}
            className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
          />
        </div>

        <div className="space-y-1.5">
          <label
            htmlFor="adjust-advance-note"
            className="text-xs font-semibold uppercase tracking-wider text-ink-muted"
          >
            {t("note")}
          </label>
          <input
            id="adjust-advance-note"
            type="text"
            value={note}
            placeholder={t("notePlaceholder")}
            onChange={(event) => setNote(event.target.value)}
            className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
          />
        </div>

        {error && (
          <p role="alert" className="text-sm text-status-critical">
            {error}
          </p>
        )}

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

