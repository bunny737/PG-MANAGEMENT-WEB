"use client";

import { useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { useTranslations } from "next-intl";
import { Dialog } from "@/components/ui/Dialog";
import { useActiveProperty } from "@/components/shared/PropertyFilter";
import { ApiError, generateInvoice, type Invoice } from "@/lib/api";
import { afterInvoiceChange } from "@/lib/refresh";
import { ResidentPicker } from "./ResidentPicker";

const schema = z.object({
  resident: z.string().min(1),
  period_start: z.string().min(1),
  period_end: z.string().min(1),
  due_date: z.string().min(1),
});
type FormValues = z.infer<typeof schema>;

interface GenerateInvoiceDialogProps {
  onClose: () => void;
  onCreated: (invoice: Invoice) => void;
}

export function GenerateInvoiceDialog({ onClose, onCreated }: GenerateInvoiceDialogProps) {
  const t = useTranslations("billing.generateDialog");
  const { propertyId } = useActiveProperty();
  const [serverError, setServerError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setValue,
    watch,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema) });

  async function onSubmit(values: FormValues) {
    setServerError(null);
    try {
      const invoice = await generateInvoice(values);
      await afterInvoiceChange({ invoiceId: invoice.id, residentId: invoice.resident, propertyId: invoice.property });
      onCreated(invoice);
    } catch (error) {
      if (error instanceof ApiError) {
        const field = error.fieldError("resident") || error.fieldError("period_start") || error.fieldError("period_end");
        if (field) {
          setError("resident", { message: field });
        } else {
          setServerError(error.message);
        }
      } else {
        setServerError(String(error));
      }
    }
  }

  return (
    <Dialog open onClose={onClose} title={t("title")} subtitle={t("subtitle")}>
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
        <div className="space-y-1.5">
          <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">{t("resident")}</label>
          <ResidentPicker
            propertyId={propertyId}
            value={watch("resident") ?? ""}
            onChange={(id) => setValue("resident", id, { shouldValidate: true })}
            placeholder={t("residentPlaceholder")}
          />
          {errors.resident && <p className="text-xs text-status-critical">{errors.resident.message}</p>}
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">{t("periodStart")}</label>
            <input
              type="date"
              {...register("period_start")}
              className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">{t("periodEnd")}</label>
            <input
              type="date"
              {...register("period_end")}
              className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
            />
          </div>
        </div>
        <div className="space-y-1.5">
          <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">{t("dueDate")}</label>
          <input
            type="date"
            {...register("due_date")}
            className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
          />
        </div>
        {serverError && <p className="text-sm text-status-critical">{serverError}</p>}
        <button
          type="submit"
          disabled={isSubmitting}
          className="w-full rounded-xl bg-accent py-2.5 text-sm font-semibold text-ink-inverse transition-colors hover:bg-accent-hover disabled:opacity-60 cursor-pointer"
        >
          {isSubmitting ? t("submitting") : t("submit")}
        </button>
      </form>
    </Dialog>
  );
}
