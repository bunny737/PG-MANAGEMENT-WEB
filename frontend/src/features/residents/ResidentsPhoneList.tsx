"use client";

import Link from "next/link";
import { Phone, UserPlus } from "lucide-react";
import { useTranslations } from "next-intl";
import { Fab } from "@/components/mobile/Fab";
import { FilterChip } from "@/components/mobile/FilterChip";
import { MobileTopBar } from "@/components/mobile/MobileTopBar";
import { PropertyPill } from "@/components/mobile/PropertyPill";
import { SearchField } from "@/components/mobile/SearchField";
import { StatusBadge } from "@/components/mobile/StatusBadge";
import { PermissionGate } from "@/components/shared/PermissionGate";
import { SectionError, SectionSkeleton } from "@/components/shared/SectionState";
import type { Resident } from "@/lib/api";
import { formatMoneyCompact } from "@/lib/money";
import { useSession } from "@/lib/session";

export const PHONE_STATUS_TABS = ["all", "active", "notice_period", "vacated"] as const;
export type PhoneStatusTab = (typeof PHONE_STATUS_TABS)[number];

const CHIP_KEYS: Record<PhoneStatusTab, "chipAll" | "chipActive" | "chipNotice" | "chipVacated"> = {
  all: "chipAll",
  active: "chipActive",
  notice_period: "chipNotice",
  vacated: "chipVacated",
};

/**
 * What a resident card says about rent, decided by permission first. `contracted_rent` is redacted by the
 * API without `view_finance`, so its absence there means "hidden", not "not set":
 *   no view_finance            -> nothing
 *   view_finance, value        -> the amount
 *   view_finance, null/missing -> "rent not set"
 */
export function rentLine(
  canSeeFinance: boolean,
  contractedRent: string | null | undefined,
  format: (amount: string) => string,
  notSet: string
): string | null {
  if (!canSeeFinance) return null;
  return contractedRent ? format(contractedRent) : notSet;
}

interface ResidentsPhoneListProps {
  residents: Resident[];
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
  searchTerm: string;
  onSearchChange: (value: string) => void;
  status: PhoneStatusTab;
  onStatusChange: (status: PhoneStatusTab) => void;
}

/** Phone residents screen (< md): top bar with property pill, search, status chips, resident cards, Admit FAB. */
export function ResidentsPhoneList({
  residents,
  isLoading,
  isError,
  onRetry,
  searchTerm,
  onSearchChange,
  status,
  onStatusChange,
}: ResidentsPhoneListProps) {
  const t = useTranslations("residents.directory");
  const tStatus = useTranslations("status");
  const { can } = useSession();
  const canSeeFinance = can("view_finance");

  return (
    <div className="pb-28 md:hidden">
      <MobileTopBar title={t("phoneTitle")} trailing={<PropertyPill />} />

      <div className="flex flex-col gap-4 px-4 pt-2">
        <SearchField
          label={t("phoneSearchLabel")}
          placeholder={t("phoneSearchPlaceholder")}
          value={searchTerm}
          onChange={(event) => onSearchChange(event.target.value)}
        />

        <div role="radiogroup" aria-label={t("chipsLabel")} className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1">
          {PHONE_STATUS_TABS.map((tab) => (
            <FilterChip key={tab} label={t(CHIP_KEYS[tab])} selected={status === tab} onClick={() => onStatusChange(tab)} />
          ))}
        </div>

        {isLoading && <SectionSkeleton className="h-48" />}
        {isError && <SectionError onRetry={onRetry} message={t("errLoadFailed")} />}

        {!isLoading && !isError && residents.length === 0 && (
          <div className="rounded-2xl border border-m3-outline-variant bg-m3-surface px-4 py-10 text-center">
            <p className="text-lg font-medium text-m3-on-surface">{t("emptyTitle")}</p>
            <p className="mt-1 text-base text-m3-on-surface-variant">{t("emptyDesc")}</p>
          </div>
        )}

        {!isLoading && !isError && residents.length > 0 && (
          <ul className="flex flex-col gap-3">
            {residents.map((resident) => {
              const fullName = `${resident.first_name} ${resident.last_name}`.trim();
              const rent = rentLine(
                canSeeFinance,
                resident.contracted_rent,
                (amount) => t("rentMonthly", { amount: formatMoneyCompact(amount) }),
                t("rentNotSet")
              );
              return (
                <li key={resident.id}>
                  <Link
                    href={`/residents/${resident.id}`}
                    className="flex items-center gap-4 rounded-2xl border border-m3-outline-variant bg-m3-surface p-4 active:bg-m3-surface-container-high"
                  >
                    <span
                      aria-hidden
                      className="flex size-14 shrink-0 items-center justify-center rounded-full bg-m3-primary-container text-xl font-medium text-m3-on-primary-container"
                    >
                      {(resident.first_name || fullName).charAt(0).toUpperCase()}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-lg leading-6 font-bold text-m3-on-surface">{fullName}</p>
                      <p className="flex flex-wrap items-center gap-x-1.5 text-base leading-6 text-m3-on-surface-variant">
                        <Phone className="size-4 shrink-0" aria-hidden />
                        <span>{resident.phone}</span>
                        {rent && (
                          <>
                            <span aria-hidden>·</span>
                            <span>{rent}</span>
                          </>
                        )}
                      </p>
                    </div>
                    <StatusBadge status={resident.status} label={tStatus(resident.status)} />
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <PermissionGate permission="manage_admissions">
        <Fab href="/admissions" label={t("admitResident")} icon={<UserPlus className="size-6" />} />
      </PermissionGate>
    </div>
  );
}
