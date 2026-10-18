"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { Sheet } from "@/components/ui/Sheet";
import {
  ApiError,
  createExpense,
  type Expense,
  type ExpenseCategory,
  type ExpenseMode,
  listProperties,
  updateExpense,
} from "@/lib/api";
import { afterExpenseChange } from "@/lib/refresh";
import { createIdempotencyKey } from "@/lib/idempotency";

const MODES: ExpenseMode[] = ["cash", "upi", "bank_transfer", "card", "cheque", "other"];
const MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024;
const ALLOWED_ATTACHMENT_TYPES = ["image/jpeg", "image/png", "image/webp", "application/pdf"];

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

interface ExpenseFormSheetProps {
  initial?: Expense;
  /** Prefills from an existing expense but as a brand-new one, dated today —
   * the one-tap "Repeat" preset. */
  repeatFrom?: Expense;
  defaultProperty: string | null;
  categories: ExpenseCategory[];
  viewedMonth: string;
  onClose: () => void;
  /** Called with the expense's month when it differs from `viewedMonth` —
   * the "Saved to Sep 2026 — View" toast's View action. */
  onViewMonth: (month: string) => void;
}

export function ExpenseFormSheet({
  initial,
  repeatFrom,
  defaultProperty,
  categories,
  viewedMonth,
  onClose,
  onViewMonth,
}: ExpenseFormSheetProps) {
  const t = useTranslations("expenses.form");
  const tAttachment = useTranslations("expenses.attachment");
  const tStatus = useTranslations("status");
  const source = initial ?? repeatFrom;
  const { data: properties = [] } = useQuery({ queryKey: ["properties", "list"], queryFn: listProperties });

  const [idempotencyKey] = useState(createIdempotencyKey);
  const [property, setProperty] = useState(source?.property ?? defaultProperty ?? "");
  const [category, setCategory] = useState(source?.category ?? categories[0]?.id ?? "");
  const [amount, setAmount] = useState(source?.amount ?? "");
  const [date, setDate] = useState(initial ? initial.date : todayISO());
  const [mode, setMode] = useState<ExpenseMode>(source?.payment_mode ?? "cash");
  const [note, setNote] = useState(source?.note ?? "");
  const [attachment, setAttachment] = useState<File | null>(null);
  const [attachmentError, setAttachmentError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [savedToMonth, setSavedToMonth] = useState<string | null>(null);

  const activeCategories = categories.filter((c) => !c.is_archived || c.id === category);

  function handleFile(file: File | null) {
    setAttachmentError(null);
    if (!file) {
      setAttachment(null);
      return;
    }
    if (file.size > MAX_ATTACHMENT_BYTES) {
      setAttachmentError(tAttachment("tooLarge"));
      return;
    }
    if (!ALLOWED_ATTACHMENT_TYPES.includes(file.type)) {
      setAttachmentError(tAttachment("wrongType"));
      return;
    }
    setAttachment(file);
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!property) {
      setError(t("propertyRequired"));
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      if (initial) {
        await updateExpense(initial.id, { property, category, amount, date, payment_mode: mode, note });
      } else {
        await createExpense(
          { property, category, amount, date, payment_mode: mode, note, attachment: attachment ?? undefined },
          idempotencyKey
        );
      }
      await afterExpenseChange();
      const savedMonth = date.slice(0, 7);
      if (savedMonth !== viewedMonth) {
        setSavedToMonth(savedMonth);
      } else {
        onClose();
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Sheet open onClose={onClose} title={initial ? t("editTitle") : t("addTitle")}>
      {savedToMonth ? (
        <div className="space-y-4">
          <p className="text-sm text-ink">{t("success")}</p>
          <button
            type="button"
            onClick={() => onViewMonth(savedToMonth)}
            className="w-full rounded-xl bg-accent py-2.5 text-sm font-semibold text-ink-inverse hover:bg-accent-hover cursor-pointer"
          >
            {t("savedToMonth", { month: savedToMonth })}
          </button>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">{t("property")}</label>
            <select
              value={property}
              onChange={(event) => setProperty(event.target.value)}
              className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
            >
              <option value="">—</option>
              {properties.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">{t("category")}</label>
            <select
              value={category}
              onChange={(event) => setCategory(event.target.value)}
              className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
            >
              {activeCategories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label}
                </option>
              ))}
            </select>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">{t("amount")}</label>
              <input
                type="text"
                inputMode="decimal"
                value={amount}
                onChange={(event) => setAmount(event.target.value)}
                required
                className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">{t("date")}</label>
              <input
                type="date"
                value={date}
                max={todayISO()}
                onChange={(event) => setDate(event.target.value)}
                className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
              />
            </div>
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">{t("mode")}</label>
            <select
              value={mode}
              onChange={(event) => setMode(event.target.value as ExpenseMode)}
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
            <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">{t("note")}</label>
            <input
              type="text"
              value={note}
              onChange={(event) => setNote(event.target.value)}
              className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
            />
          </div>
          {!initial && (
            <div className="space-y-1.5">
              <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">{t("attachment")}</label>
              <input
                type="file"
                accept="image/jpeg,image/png,image/webp,application/pdf"
                onChange={(event) => handleFile(event.target.files?.[0] ?? null)}
                className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none"
              />
              <p className="text-xs text-ink-faint">{t("attachmentHint")}</p>
              {attachmentError && <p className="text-xs text-status-critical">{attachmentError}</p>}
            </div>
          )}
          {error && <p className="text-sm text-status-critical">{error}</p>}
          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-xl bg-accent py-2.5 text-sm font-semibold text-ink-inverse transition-colors hover:bg-accent-hover disabled:opacity-60 cursor-pointer"
          >
            {submitting ? t("submitting") : t("submit")}
          </button>
        </form>
      )}
    </Sheet>
  );
}
