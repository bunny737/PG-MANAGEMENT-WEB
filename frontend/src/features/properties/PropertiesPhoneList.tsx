"use client";

import Link from "next/link";
import { Building2, ChevronRight, Store } from "lucide-react";
import { useTranslations } from "next-intl";
import { Fab } from "@/components/mobile/Fab";
import { MobileTopBar } from "@/components/mobile/MobileTopBar";
import { PropertyPill } from "@/components/mobile/PropertyPill";
import { PermissionGate } from "@/components/shared/PermissionGate";
import { useActiveProperty } from "@/components/shared/PropertyFilter";
import { SectionError, SectionSkeleton } from "@/components/shared/SectionState";
import type { Property } from "@/lib/api";

/** The properties the pill selects: one property, or all of them for "All Properties". */
export function filterByActiveProperty<T extends { id: string }>(properties: T[], propertyId: string | null): T[] {
  return propertyId ? properties.filter((property) => property.id === propertyId) : properties;
}

interface PropertiesPhoneListProps {
  /** null while loading. */
  properties: Property[] | null;
  error: string;
  onRetry: () => void;
}

/** Phone properties screen (< md): top bar with property pill, compact property cards, Add Property FAB. */
export function PropertiesPhoneList({ properties, error, onRetry }: PropertiesPhoneListProps) {
  const t = useTranslations("properties");
  const { propertyId } = useActiveProperty();
  const visible = properties ? filterByActiveProperty(properties, propertyId) : null;

  return (
    <div className="pb-28 md:hidden">
      <MobileTopBar title={t("list.phoneTitle")} trailing={<PropertyPill />} />

      <div className="flex flex-col gap-3 px-4 pt-2">
        {error && <SectionError onRetry={onRetry} message={error} />}
        {!error && visible === null && <SectionSkeleton className="h-40" />}

        {!error && visible && visible.length === 0 && (
          <div className="rounded-2xl border border-m3-outline-variant bg-m3-surface px-4 py-10 text-center">
            <p className="text-lg font-medium text-m3-on-surface">
              {properties && properties.length > 0 ? t("list.noMatch") : t("list.emptyTitle")}
            </p>
            {properties && properties.length === 0 && (
              <p className="mt-1 text-base text-m3-on-surface-variant">{t("list.emptyDesc")}</p>
            )}
          </div>
        )}

        {!error && visible && visible.length > 0 && (
          <ul className="flex flex-col gap-3">
            {visible.map((property) => (
              <li key={property.id}>
                <Link
                  href={`/properties/${property.id}`}
                  className="flex items-center gap-4 rounded-2xl border border-m3-outline-variant bg-m3-surface p-4 active:bg-m3-surface-container-high"
                >
                  <span
                    aria-hidden
                    className="flex size-14 shrink-0 items-center justify-center rounded-full bg-m3-primary-container text-m3-on-primary-container"
                  >
                    <Building2 className="size-7" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-lg leading-6 font-bold text-m3-on-surface">{property.name}</p>
                    <p className="text-base leading-6 text-m3-on-surface-variant">
                      {[property.city, property.state].filter(Boolean).join(", ")}
                      {" · "}
                      <span className="uppercase">{t(`typesShort.${property.property_type}`)}</span>
                    </p>
                  </div>
                  <ChevronRight className="size-6 shrink-0 text-m3-on-surface" aria-hidden />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>

      <PermissionGate permission="manage_properties">
        <Fab href="/properties/add" label={t("list.addProperty")} icon={<Store className="size-6" />} />
      </PermissionGate>
    </div>
  );
}
