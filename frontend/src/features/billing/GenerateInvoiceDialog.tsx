"use client";

import { useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { Controller, useForm } from "react-hook-form";
import { z } from "zod";
import { useTranslations } from "next-intl";
import { Dialog } from "@/components/ui/Dialog";
import { DatePicker } from "@/components/ui/DatePicker";
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
  /** Pre-selects and locks the resident (e.g. opened from a resident's
   * finance card) instead of offering the ResidentPicker. */
  residentId?: string;
  residentName?: string;
  /** Overrides the active-property scope for the ResidentPicker — needed
   * when opened from a resident whose property isn't the active selection. */
  propertyId?: string | null;
}

export function GenerateInvoiceDialog({
  onClose,
  onCreated,
  residentId,
  residentName,
  propertyId: propertyIdProp,
}: GenerateInvoiceDialogProps) {
  const t = useTranslations("billing.generateDialog");
  const { propertyId: activePropertyId } = useActiveProperty();
  const propertyId = propertyIdProp ?? activePropertyId;
  const [serverError, setServerError] = useState<string | null>(null);
  const {
    handleSubmit,
    setValue,
    watch,
    control,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    // "" (not undefined) so an untouched picker fails min(1), not invalid_type.
    defaultValues: {
      resident: residentId ?? "",
      period_start: "",
      period_end: "",
      due_date: "",
    },
  });

  async function onSubmit(values: FormValues) {
    setServerError(null);
    try {
      const invoice = await generateInvoice(values);
      await afterInvoiceChange({ invoiceId: invoice.id, residentId: invoice.resident, propertyId: invoice.property });
      onCreated(invoice);
    } catch (error) {
      if (error instanceof ApiError) {
        const resErr = error.fieldError("resident");
        const startErr = error.fieldError("period_start");
        const endErr = error.fieldError("period_end");
        const dueErr = error.fieldError("due_date");
        if (resErr) {
          setError("resident", { message: resErr });
        } else if (startErr) {
          setError("period_start", { message: startErr });
        } else if (endErr) {
          setError("period_end", { message: endErr });
        } else if (dueErr) {
          setError("due_date", { message: dueErr });
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
          {residentId ? (
            <input
              type="text"
              disabled
              value={residentName ?? residentId}
              className="w-full rounded-xl border border-border bg-surface-page px-3 py-2 text-sm text-ink-muted"
            />
          ) : (
            <ResidentPicker
              propertyId={propertyId}
              value={watch("resident") ?? ""}
              onChange={(id) => setValue("resident", id, { shouldValidate: true })}
              placeholder={t("residentPlaceholder")}
            />
          )}
          {errors.resident && (
            <p className="text-xs text-status-critical">
              {errors.resident.type === "too_small" ? t("residentRequired") : errors.resident.message}
            </p>
          )}
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">{t("periodStart")}</label>
            <Controller
              control={control}
              name="period_start"
              render={({ field }) => (
                <DatePicker
                  value={field.value}
                  onChange={field.onChange}
                  error={!!errors.period_start}
                  placeholder="DD-MM-YYYY"
                />
              )}
            />
            {errors.period_start && (
              <p className="text-xs text-status-critical">{errors.period_start.message}</p>
            )}
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">{t("periodEnd")}</label>
            <Controller
              control={control}
              name="period_end"
              render={({ field }) => (
                <DatePicker
                  value={field.value}
                  onChange={field.onChange}
                  error={!!errors.period_end}
                  placeholder="DD-MM-YYYY"
                />
              )}
            />
            {errors.period_end && (
              <p className="text-xs text-status-critical">{errors.period_end.message}</p>
            )}
          </div>
        </div>
        <div className="space-y-1.5">
          <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">{t("dueDate")}</label>
          <Controller
            control={control}
            name="due_date"
            render={({ field }) => (
              <DatePicker
                value={field.value}
                onChange={field.onChange}
                error={!!errors.due_date}
                placeholder="DD-MM-YYYY"
              />
            )}
          />
          {errors.due_date && (
            <p className="text-xs text-status-critical">{errors.due_date.message}</p>
          )}
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
