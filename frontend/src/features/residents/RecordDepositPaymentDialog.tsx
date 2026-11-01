"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Dialog } from "@/components/ui/Dialog";
import { ApiError, createDepositPayment, type DepositMode, type Resident } from "@/lib/api";
import { localDateKey } from "@/lib/date";
import { createIdempotencyKey } from "@/lib/idempotency";
import { compareMoney, formatMoney, isAtMost, isMoneyInput, toMoneyString, ZERO } from "@/lib/money";

const MODES: DepositMode[] = ["cash", "upi", "bank_transfer"];

// The local calendar day, not UTC: between midnight and 05:30 IST the UTC date is still yesterday.
const todayISO = () => localDateKey(new Date());

interface RecordDepositPaymentDialogProps {
  resident: Resident;
  onClose: () => void;
  /** Fired once after a successful record (201 or a 200 replay), so the profile can reload. */
  onRecorded?: () => void;
}

/** Records a later collection of a resident's security deposit (Module 10): the part still pending after
 * admission. Needs manage_deposits. One Idempotency-Key per dialog, so a double tap or a flaky-network retry
 * can't record the same payment twice. */
export function RecordDepositPaymentDialog({ resident, onClose, onRecorded }: RecordDepositPaymentDialogProps) {
  const t = useTranslations("residents.profile.depositDialog");
  const tStatus = useTranslations("status");
  const pending = resident.security_deposit_pending ?? ZERO;
  const [idempotencyKey] = useState(createIdempotencyKey);
  const [amount, setAmount] = useState(pending);
  const [mode, setMode] = useState<DepositMode>("cash");
  const [date, setDate] = useState(todayISO);
  const [reference, setReference] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [recorded, setRecorded] = useState<{ replayed: boolean } | null>(null);

  const fullName = [resident.first_name, resident.last_name].filter(Boolean).join(" ");

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const value = amount.trim();
    if (!isMoneyInput(value) || compareMoney(value, ZERO) !== 1) {
      setError(t("errAmount"));
      return;
    }
    if (!isAtMost(value, pending)) {
      setError(t("errExceeds"));
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      const { replayed } = await createDepositPayment(
        { resident: resident.id, amount: toMoneyString(value), payment_date: date, payment_mode: mode, reference: reference || undefined },
        idempotencyKey,
      );
      setRecorded({ replayed });
      onRecorded?.();
    } catch (err) {
      if (err instanceof ApiError) {
        // Validation errors (overpaid, resident no longer current) carry their own message on a field;
        // only IDEMPOTENCY_KEY_REUSED is a top-level code (409).
        const fieldMessage = err.fieldError("amount") ?? err.fieldError("resident");
        if (fieldMessage) setError(fieldMessage);
        else if (err.code === "IDEMPOTENCY_KEY_REUSED") setError(t("errReused"));
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
    <Dialog open onClose={onClose} title={t("title")} subtitle={t("subtitle", { resident: fullName, pending: formatMoney(pending) })}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-1.5">
          <label htmlFor="deposit-amount" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
            {t("amount")}
          </label>
          <input
            id="deposit-amount"
            type="text"
            inputMode="decimal"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <label htmlFor="deposit-mode" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
              {t("mode")}
            </label>
            <select
              id="deposit-mode"
              value={mode}
              onChange={(event) => setMode(event.target.value as DepositMode)}
              className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
            >
              {MODES.map((m) => (
                <option key={m} value={m}>
                  {tStatus(m)}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1.5">
            <label htmlFor="deposit-date" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
              {t("date")}
            </label>
            <input
              id="deposit-date"
              type="date"
              value={date}
              max={todayISO()}
              onChange={(event) => setDate(event.target.value)}
              className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
            />
          </div>
        </div>
        <div className="space-y-1.5">
          <label htmlFor="deposit-reference" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
            {t("reference")}
          </label>
          <input
            id="deposit-reference"
            type="text"
            value={reference}
            onChange={(event) => setReference(event.target.value)}
            className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
          />
        </div>
        {error && <p role="alert" className="text-sm text-status-critical">{error}</p>}
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
