"use client";

import { useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { useTranslations } from "next-intl";
import { Dialog } from "@/components/ui/Dialog";
import { useActiveProperty } from "@/components/shared/PropertyFilter";
import { ApiError, bulkGenerateInvoices, listProperties } from "@/lib/api";
import { afterInvoiceChange } from "@/lib/refresh";
import { queryKeys } from "@/lib/queryKeys";

const schema = z.object({
  property: z.string().min(1),
  period_start: z.string().min(1),
  period_end: z.string().min(1),
  due_date: z.string().min(1),
});
type FormValues = z.infer<typeof schema>;

export function BulkGenerateDialog({ onClose }: { onClose: () => void }) {
  const t = useTranslations("billing.bulkGenerateDialog");
  const { propertyId } = useActiveProperty();
  const { data: properties = [] } = useQuery({ queryKey: queryKeys.properties.list, queryFn: listProperties });
  const [result, setResult] = useState<string | null>(null);
  const [serverError, setServerError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { property: propertyId ?? "" },
  });

  async function onSubmit(values: FormValues) {
    setServerError(null);
    try {
      const { created } = await bulkGenerateInvoices(values);
      await afterInvoiceChange({ propertyId: values.property });
      setResult(t("success", { count: created }));
    } catch (error) {
      setServerError(error instanceof ApiError ? error.message : String(error));
    }
  }

  return (
    <Dialog open onClose={onClose} title={t("title")} subtitle={t("subtitle")}>
      {result ? (
        <div className="space-y-4">
          <p className="text-sm text-ink">{result}</p>
          <button
            type="button"
            onClick={onClose}
            className="w-full rounded-xl bg-accent py-2.5 text-sm font-semibold text-ink-inverse transition-colors hover:bg-accent-hover cursor-pointer"
          >
            {t("submit")}
          </button>
        </div>
      ) : (
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">{t("property")}</label>
            <select
              {...register("property")}
              className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
            >
              <option value="">—</option>
              {properties.map((property) => (
                <option key={property.id} value={property.id}>
                  {property.name}
                </option>
              ))}
            </select>
            {errors.property && <p className="text-xs text-status-critical">{errors.property.message}</p>}
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
      )}
    </Dialog>
  );
}
