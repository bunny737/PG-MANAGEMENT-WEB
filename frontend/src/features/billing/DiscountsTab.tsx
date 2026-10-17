"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { Percent, Plus } from "lucide-react";
import { type Discount, type DiscountFilters, endDiscount, listDiscountsFiltered } from "@/lib/api";
import { MoneyText } from "@/components/shared/MoneyText";
import { PermissionGate } from "@/components/shared/PermissionGate";
import { PropertyFilter, useActiveProperty } from "@/components/shared/PropertyFilter";
import { SectionError, SectionSkeleton } from "@/components/shared/SectionState";
import { queryKeys } from "@/lib/queryKeys";
import { afterDiscountChange } from "@/lib/refresh";
import { DiscountFormDialog } from "./DiscountFormDialog";

export function DiscountsTab() {
  const t = useTranslations("billing.discounts");
  const tReason = useTranslations("billing.discountReason");
  const { propertyId } = useActiveProperty();
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);

  const filters: DiscountFilters = { property: propertyId ?? undefined };
  const { data: discounts = [], isLoading, isError, refetch } = useQuery({
    queryKey: queryKeys.discounts.list(filters),
    queryFn: () => listDiscountsFiltered(filters),
  });

  const endMutation = useMutation({
    mutationFn: (discount: Discount) => endDiscount(discount.id, new Date().toISOString().slice(0, 10)),
    onSuccess: async (_void, discount) => {
      await afterDiscountChange({ residentId: discount.resident });
      queryClient.invalidateQueries({ queryKey: queryKeys.discounts.all });
    },
  });

  function handleEnd(discount: Discount) {
    if (window.confirm(t("endConfirmBody"))) endMutation.mutate(discount);
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <PropertyFilter />
        <PermissionGate permission="manage_discounts">
          <button
            type="button"
            onClick={() => setShowForm(true)}
            className="inline-flex items-center gap-1.5 rounded-xl bg-accent px-3 py-2 text-sm font-semibold text-ink-inverse transition-colors hover:bg-accent-hover cursor-pointer"
          >
            <Plus className="size-4" />
            {t("add")}
          </button>
        </PermissionGate>
      </div>

      {isLoading && <SectionSkeleton className="h-64" />}
      {isError && <SectionError onRetry={() => refetch()} message={t("errLoadFailed")} />}

      {!isLoading && !isError && discounts.length === 0 && (
        <div className="flex flex-col items-center gap-2 rounded-2xl border border-border bg-surface-card p-12 text-center">
          <Percent className="size-8 text-ink-faint" />
          <h3 className="text-sm font-bold text-ink">{t("emptyTitle")}</h3>
          <p className="text-xs text-ink-muted">{t("emptyDesc")}</p>
        </div>
      )}

      {!isLoading && !isError && discounts.length > 0 && (
        <div className="overflow-hidden rounded-2xl border border-border bg-surface-card">
          <div className="hidden grid-cols-12 gap-4 border-b border-border bg-surface-page px-5 py-3 text-xs font-bold uppercase tracking-wider text-ink-muted md:grid">
            <div className="col-span-3">{t("table.resident")}</div>
            <div className="col-span-2">{t("table.roomBed")}</div>
            <div className="col-span-2">{t("table.value")}</div>
            <div className="col-span-2">{t("table.reason")}</div>
            <div className="col-span-2">{t("table.validity")}</div>
            <div className="col-span-1" />
          </div>
          <div className="divide-y divide-border">
            {discounts.map((discount) => {
              const active = !discount.valid_until || discount.valid_until >= new Date().toISOString().slice(0, 10);
              return (
                <div key={discount.id} className="grid grid-cols-1 gap-2 px-5 py-3.5 text-sm md:grid-cols-12 md:items-center md:gap-4">
                  <div className="col-span-3 font-semibold text-ink">{discount.resident_name}</div>
                  <div className="col-span-2 text-ink-muted">
                    {discount.room_number ? `${discount.room_number} / ${discount.bed_number}` : "—"}
                  </div>
                  <div className="col-span-2">
                    {discount.discount_type === "percentage" ? (
                      `${discount.discount_value}%`
                    ) : (
                      <MoneyText value={discount.discount_value} />
                    )}
                  </div>
                  <div className="col-span-2 text-ink-muted">{tReason(discount.reason)}</div>
                  <div className="col-span-2 text-ink-muted">
                    {discount.valid_from} – {discount.valid_until ?? t("indefinite")}
                  </div>
                  <div className="col-span-1 flex md:justify-end">
                    {active && (
                      <PermissionGate permission="manage_discounts">
                        <button
                          type="button"
                          onClick={() => handleEnd(discount)}
                          className="text-xs font-semibold text-status-critical hover:underline cursor-pointer"
                        >
                          {t("end")}
                        </button>
                      </PermissionGate>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {showForm && <DiscountFormDialog onClose={() => setShowForm(false)} />}
    </div>
  );
}
