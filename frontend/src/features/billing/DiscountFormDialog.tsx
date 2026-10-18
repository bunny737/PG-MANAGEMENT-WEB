"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Dialog } from "@/components/ui/Dialog";
import { useActiveProperty } from "@/components/shared/PropertyFilter";
import { ApiError, createDiscount, type Discount, type DiscountReason, type DiscountType } from "@/lib/api";
import { afterDiscountChange } from "@/lib/refresh";
import { ResidentPicker } from "./ResidentPicker";

const REASONS: DiscountReason[] = ["loyalty", "referral", "corporate", "negotiated", "seasonal", "other"];

export function DiscountFormDialog({ onClose }: { onClose: () => void }) {
  const t = useTranslations("billing.discountForm");
  const tReason = useTranslations("billing.discountReason");
  const { propertyId } = useActiveProperty();
  const [resident, setResident] = useState("");
  const [discountType, setDiscountType] = useState<DiscountType>("fixed");
  const [value, setValue] = useState("");
  const [reason, setReason] = useState<DiscountReason>("other");
  const [note, setNote] = useState("");
  const [validFrom, setValidFrom] = useState(new Date().toISOString().slice(0, 10));
  const [validUntil, setValidUntil] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!resident) {
      setError(t("resident"));
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      const discount: Discount = await createDiscount({
        resident,
        discount_type: discountType,
        discount_value: value,
        reason,
        note: note || undefined,
        valid_from: validFrom,
        valid_until: validUntil || undefined,
      });
      await afterDiscountChange({ residentId: discount.resident });
      onClose();
    } catch (err) {
      if (err instanceof ApiError) {
        // Field-level ValidationError codes (overlapping_discount, ...) don't
        // survive to JSON — the backend's own message on the field is the
        // reliable source, including for the overlap case (errOverlap is
        // unused here but kept as a fallback label).
        setError(err.fieldError("valid_from") ?? err.fieldError("discount_value") ?? err.fieldError("resident") ?? err.message ?? t("errOverlap"));
      } else {
        setError(String(err));
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open onClose={onClose} title={t("addTitle")}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-1.5">
          <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">{t("resident")}</label>
          <ResidentPicker
            propertyId={propertyId}
            value={resident}
            onChange={setResident}
            placeholder={t("residentPlaceholder")}
            statuses="active,notice_period,inquiry,reserved"
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">{t("type")}</label>
            <select
              value={discountType}
              onChange={(event) => setDiscountType(event.target.value as DiscountType)}
              className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
            >
              <option value="fixed">{t("typeFixed")}</option>
              <option value="percentage">{t("typePercentage")}</option>
            </select>
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">{t("value")}</label>
            <input
              type="text"
              inputMode="decimal"
              value={value}
              onChange={(event) => setValue(event.target.value)}
              required
              className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
            />
          </div>
        </div>
        <div className="space-y-1.5">
          <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">{t("reason")}</label>
          <select
            value={reason}
            onChange={(event) => setReason(event.target.value as DiscountReason)}
            className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
          >
            {REASONS.map((r) => (
              <option key={r} value={r}>
                {tReason(r)}
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
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">{t("validFrom")}</label>
            <input
              type="date"
              value={validFrom}
              onChange={(event) => setValidFrom(event.target.value)}
              className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">{t("validUntil")}</label>
            <input
              type="date"
              value={validUntil}
              onChange={(event) => setValidUntil(event.target.value)}
              className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
            />
          </div>
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
