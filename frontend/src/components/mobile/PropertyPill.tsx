"use client";

import { Building2, ChevronDown } from "lucide-react";
import { useTranslations } from "next-intl";
import { useActiveProperty } from "@/components/shared/PropertyFilter";
import { cn } from "@/lib/utils";

/**
 * The property picker as a pill (building icon, name, chevron), like the Android app. A native
 * <select> is laid over the whole pill, invisible but focusable, so a tap opens the platform's own
 * picker (the iOS wheel) and keyboards and screen readers get a real control. The choice goes to the
 * shared active-property store, so it carries across Dashboard, Residents, Properties and Vacancies.
 */
export function PropertyPill({ className, wide = false }: { className?: string; wide?: boolean }) {
  const t = useTranslations("common");
  const { propertyId, properties, accessRevoked, setPropertyId } = useActiveProperty();
  const selected = properties.find((property) => property.id === propertyId);
  const label = selected?.name ?? t("propertyFilter.all");

  return (
    <div className={cn("flex flex-col gap-1", wide ? "items-stretch" : "items-end", className)}>
      <div className={cn("relative flex h-12 min-w-0 items-center gap-2 rounded-xl bg-m3-surface-container-high ps-3 pe-2 text-m3-on-surface focus-within:ring-2 focus-within:ring-m3-primary", wide ? "w-full" : "max-w-[11.5rem]")}>
        <Building2 className="size-5 shrink-0" aria-hidden />
        <span className="min-w-0 flex-1 truncate text-base font-medium">{label}</span>
        <ChevronDown className="size-5 shrink-0" aria-hidden />
        <select
          aria-label={t("phone.propertyPicker")}
          value={propertyId ?? ""}
          onChange={(event) => setPropertyId(event.target.value || null)}
          className="absolute inset-0 size-full cursor-pointer opacity-0"
        >
          <option value="">{t("propertyFilter.all")}</option>
          {properties.map((property) => (
            <option key={property.id} value={property.id}>
              {property.name}
            </option>
          ))}
        </select>
      </div>
      {accessRevoked && <p className="text-xs text-m3-critical">{t("propertyFilter.accessRevoked")}</p>}
    </div>
  );
}
