"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Dialog } from "@/components/ui/Dialog";
import { ApiError, type InvoiceLineItem, type LineType } from "@/lib/api";

const LINE_TYPES: LineType[] = ["accommodation", "food", "electricity", "water", "laundry", "addon", "additional", "discount"];

interface AddLineItemDialogProps {
  initial?: InvoiceLineItem;
  onClose: () => void;
  onSubmit: (values: { line_type: LineType; label: string; amount: string }) => Promise<unknown>;
}

export function AddLineItemDialog({ initial, onClose, onSubmit }: AddLineItemDialogProps) {
  const t = useTranslations("billing.addLineDialog");
  const tLineType = useTranslations("billing.lineType");
  const [lineType, setLineType] = useState<LineType>(initial?.line_type ?? "additional");
  const [label, setLabel] = useState(initial?.label ?? "");
  const [amount, setAmount] = useState(initial?.amount ?? "");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await onSubmit({ line_type: lineType, label, amount });
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open onClose={onClose} title={initial ? t("editTitle") : t("title")}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-1.5">
          <select
            value={lineType}
            onChange={(event) => setLineType(event.target.value as LineType)}
            className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
          >
            {LINE_TYPES.map((type) => (
              <option key={type} value={type}>
                {tLineType(type)}
              </option>
            ))}
          </select>
        </div>
        <input
          type="text"
          value={label}
          onChange={(event) => setLabel(event.target.value)}
          required
          className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
        />
        <input
          type="text"
          inputMode="decimal"
          value={amount}
          onChange={(event) => setAmount(event.target.value)}
          required
          className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
        />
        {error && <p className="text-sm text-status-critical">{error}</p>}
        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded-xl bg-accent py-2.5 text-sm font-semibold text-ink-inverse transition-colors hover:bg-accent-hover disabled:opacity-60 cursor-pointer"
        >
          {initial ? t("save") : t("submit")}
        </button>
      </form>
    </Dialog>
  );
}
