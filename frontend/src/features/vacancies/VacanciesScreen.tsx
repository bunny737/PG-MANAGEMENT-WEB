"use client";

import Link from "next/link";
import { useQueries } from "@tanstack/react-query";
import { BedDouble, Building2, CalendarCheck, ChevronRight, Plus, User } from "lucide-react";
import { useTranslations } from "next-intl";
import { MobileTopBar } from "@/components/mobile/MobileTopBar";
import { PropertyPill } from "@/components/mobile/PropertyPill";
import { SummaryTile } from "@/components/mobile/SummaryTile";
import { TonalCard } from "@/components/mobile/TonalCard";
import { PermissionGate } from "@/components/shared/PermissionGate";
import { useActiveProperty } from "@/components/shared/PropertyFilter";
import { SectionError, SectionSkeleton } from "@/components/shared/SectionState";
import { getPropertyLayout, type Property } from "@/lib/api";
import { formatDateDMY } from "@/lib/date";
import { formatMoneyCompact } from "@/lib/money";
import { queryKeys } from "@/lib/queryKeys";
import { buildPropertyVacancies, type PropertyVacancies, type VacancyRoom } from "@/lib/vacancies";

type TFn = ReturnType<typeof useTranslations<"vacancies">>;

function RoomCard({ propertyId, room, t }: { propertyId: string; room: VacancyRoom; t: TFn }) {
  const subtitle = [room.buildingName, room.floorName].filter(Boolean).join(" · ");
  const rate = formatMoneyCompact(room.rate.amount);

  return (
    <TonalCard className="p-4">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <h3 className="text-xl leading-7 font-bold text-m3-on-surface">{t("room", { number: room.roomNumber })}</h3>
        <span className="text-base text-m3-on-surface-variant">· {subtitle}</span>
        <span className="rounded-lg bg-m3-surface-container-high px-2.5 py-1 text-sm font-medium text-m3-on-surface-variant">
          {t("share", { count: room.sharingType })}
        </span>
        <span className="ms-auto text-lg font-bold text-m3-primary">
          {room.rate.isFrom ? t("rateFrom", { amount: rate }) : t("rate", { amount: rate })}
        </span>
      </div>

      {room.vacantBeds.length > 0 && (
        <div className="mt-4">
          <p className="text-sm font-bold tracking-wide text-m3-on-surface-variant uppercase">{t("vacantBedsLabel")}</p>
          <ul className="mt-2 flex flex-wrap gap-2">
            {room.vacantBeds.map((bed) => (
              <li
                key={bed.id}
                className="flex items-center gap-2 rounded-xl border border-m3-good/40 bg-m3-good-container py-2 ps-3 pe-2 text-base font-medium text-m3-good"
              >
                <BedDouble className="size-5" aria-hidden />
                {t("bed", { number: bed.number })}
                <PermissionGate permission="manage_admissions">
                  <Link
                    href={`/admissions?property=${propertyId}&bed=${bed.id}`}
                    aria-label={t("admitAria", { number: bed.number })}
                    className="flex min-h-8 items-center gap-1 rounded-lg bg-m3-primary px-3 text-sm font-medium text-m3-on-primary"
                  >
                    <Plus className="size-4" aria-hidden />
                    {t("admit")}
                  </Link>
                </PermissionGate>
              </li>
            ))}
          </ul>
        </div>
      )}

      {room.onNotice.length > 0 && (
        <div className="mt-4 border-t border-m3-outline-variant/60 pt-4">
          <p className="text-sm font-bold tracking-wide text-m3-warn uppercase">{t("onNoticeUpcoming")}</p>
          <ul className="mt-2 flex flex-col gap-2">
            {room.onNotice.map((resident) => (
              <li key={resident.residentId}>
                <Link
                  href={`/residents/${resident.residentId}`}
                  className="flex items-center gap-3 rounded-xl bg-m3-surface-container-high p-3"
                >
                  <span className="flex size-12 shrink-0 items-center justify-center rounded-full bg-m3-warn-container text-m3-warn">
                    <User className="size-6" aria-hidden />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-lg leading-6 font-bold text-m3-on-surface">
                      {resident.name}{" "}
                      <span className="text-base font-normal text-m3-on-surface-variant">
                        · {t("bed", { number: resident.bedNumber })}
                      </span>
                    </p>
                    <p className="text-base leading-6">
                      <span className="font-medium text-m3-warn">
                        {t("notice", { date: formatDateDMY(resident.noticeDate) })}
                      </span>
                      <span className="text-m3-on-surface-variant">
                        {" · "}
                        {t("vacating", { date: formatDateDMY(resident.vacatingDate) })}
                      </span>
                    </p>
                  </div>
                  <ChevronRight className="size-6 shrink-0 text-m3-on-surface" aria-hidden />
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </TonalCard>
  );
}

function PropertySection({
  property,
  data,
  t,
}: {
  property: Property;
  data: PropertyVacancies;
  t: TFn;
}) {
  const location = [property.city, property.state].filter(Boolean).join(", ");

  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-start gap-3">
        <Building2 className="mt-1 size-6 shrink-0 text-m3-primary" aria-hidden />
        <div className="min-w-0 flex-1">
          <h2 className="text-xl leading-7 font-bold text-m3-on-surface">{property.name}</h2>
          {location && <p className="text-base text-m3-on-surface-variant">{location}</p>}
          <div className="mt-2 flex flex-wrap gap-2">
            <span className="rounded-full bg-m3-good-container px-3 py-1.5 text-base font-medium text-m3-good">
              {t("nVacant", { count: data.vacantCount })}
            </span>
            {data.onNoticeCount !== null && data.onNoticeCount > 0 && (
              <span className="rounded-full bg-m3-warn-container px-3 py-1.5 text-base font-medium text-m3-warn">
                {t("nOnNotice", { count: data.onNoticeCount })}
              </span>
            )}
          </div>
        </div>
      </div>
      {data.rooms.map((room) => (
        <RoomCard key={room.id} propertyId={property.id} room={room} t={t} />
      ))}
    </section>
  );
}

/**
 * Vacancies: for every property the user can see (or the one picked), the rooms that have a vacant bed or a
 * resident on notice. One layout query per property (`useQueries`, since the number of properties varies);
 * one property failing never blanks the others.
 */
export function VacanciesScreen() {
  const t = useTranslations("vacancies");
  const { propertyId, properties, listLoaded, listError, retryList } = useActiveProperty();

  const targets = propertyId ? properties.filter((property) => property.id === propertyId) : properties;
  const queries = useQueries({
    queries: targets.map((property) => ({
      queryKey: queryKeys.properties.layout(property.id),
      queryFn: () => getPropertyLayout(property.id),
    })),
  });

  // A failed properties request never becomes "loaded", so it must not read as "still loading" forever.
  const loading = !listError && (!listLoaded || queries.some((query) => query.isPending));
  const failed = targets.flatMap((property, index) => (queries[index]?.isError ? [{ property, index }] : []));
  const loaded = targets.flatMap((property, index) => {
    const layout = queries[index]?.data;
    return layout ? [{ property, data: buildPropertyVacancies(layout) }] : [];
  });

  const vacantTotal = loaded.reduce((sum, entry) => sum + entry.data.vacantCount, 0);
  // Unknown if any loaded property hides its residents; shown only when it is a real number everywhere.
  const noticeKnown = loaded.length > 0 && loaded.every((entry) => entry.data.onNoticeCount !== null);
  const noticeTotal = loaded.reduce((sum, entry) => sum + (entry.data.onNoticeCount ?? 0), 0);
  const withRooms = loaded.filter((entry) => entry.data.rooms.length > 0);
  const allFailed = targets.length > 0 && failed.length === targets.length;

  return (
    <div className="pb-28 md:mx-auto md:max-w-3xl md:pb-8">
      <MobileTopBar title={t("title")} back="/dashboard" />
      <h1 className="hidden px-8 pt-8 text-3xl font-bold text-ink md:block">{t("title")}</h1>

      <div className="flex flex-col gap-5 px-4 pt-2 md:px-8 md:pt-6">
        {/* The property picked on another screen limits this one too, so say so (and let it be changed). */}
        {propertyId && <PropertyPill wide className="md:hidden" />}

        {listError && <SectionError message={t("loadAllFailed")} onRetry={() => void retryList()} />}

        {loading && !allFailed && <SectionSkeleton className="h-48" />}

        {allFailed && (
          <SectionError
            message={t("loadAllFailed")}
            onRetry={() => failed.forEach(({ index }) => void queries[index]?.refetch())}
          />
        )}

        {!listError && !allFailed && !loading && (
          <>
            <div className="grid grid-cols-2 gap-3">
              <SummaryTile
                tone="good"
                value={vacantTotal}
                label={t("vacantBeds")}
                icon={<BedDouble className="size-7" />}
              />
              {noticeKnown && (
                <SummaryTile
                  tone="warn"
                  value={noticeTotal}
                  label={t("onNotice")}
                  icon={<CalendarCheck className="size-7" />}
                />
              )}
            </div>

            {failed.length > 0 && <p className="text-base text-m3-on-surface-variant">{t("partial")}</p>}
          </>
        )}

        {failed.map(({ property, index }) => (
          <SectionError
            key={property.id}
            message={t("loadFailed", { name: property.name })}
            onRetry={() => void queries[index]?.refetch()}
          />
        ))}

        {!listError && !loading && !allFailed && withRooms.length === 0 && failed.length === 0 && (
          <p className="rounded-2xl border border-m3-outline-variant bg-m3-surface px-4 py-10 text-center text-base text-m3-on-surface-variant">
            {t("empty")}
          </p>
        )}

        {!loading && withRooms.map((entry) => (
          <PropertySection key={entry.property.id} property={entry.property} data={entry.data} t={t} />
        ))}
      </div>
    </div>
  );
}
