"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { AlertCircle, BedDouble } from "lucide-react";
import { getPropertyLayout, type LayoutBed, type LayoutRoom } from "@/lib/api";
import { MoneyText } from "@/components/shared/MoneyText";
import { MonthNavigator } from "@/components/shared/MonthNavigator";
import { SectionError, SectionSkeleton } from "@/components/shared/SectionState";
import { queryKeys } from "@/lib/queryKeys";
import { currentMonthKey } from "@/lib/period";
import { useSession } from "@/lib/session";
import { BedTile } from "./BedTile";

type BedFilter = "all" | "available" | "withBalance" | "onNotice";
const BED_FILTERS: BedFilter[] = ["all", "available", "withBalance", "onNotice"];

function bedMatchesFilter(bed: LayoutBed, filter: BedFilter): boolean {
  switch (filter) {
    case "available":
      return bed.availability === "available";
    case "withBalance":
      return Boolean(bed.payment && Number(bed.payment.period_balance) > 0);
    case "onNotice":
      return Boolean(bed.resident?.on_notice);
    default:
      return true;
  }
}

export function PropertyOverview({ propertyId }: { propertyId: string }) {
  const t = useTranslations("properties.layout");
  const { can } = useSession();
  const [period, setPeriod] = useState(currentMonthKey());
  const [buildingId, setBuildingId] = useState<string | null>(null);
  const [floorId, setFloorId] = useState<string | null>(null);
  const [filter, setFilter] = useState<BedFilter>("all");

  const { data: layout, isLoading, isError, refetch } = useQuery({
    queryKey: queryKeys.properties.layout(propertyId, period),
    queryFn: () => getPropertyLayout(propertyId, period),
  });

  const activeBuilding = useMemo(() => {
    if (!layout) return null;
    return layout.buildings.find((b) => b.id === buildingId) ?? layout.buildings[0] ?? null;
  }, [layout, buildingId]);

  const activeFloor = useMemo(() => {
    if (!activeBuilding) return null;
    return activeBuilding.floors.find((f) => f.id === floorId) ?? activeBuilding.floors[0] ?? null;
  }, [activeBuilding, floorId]);

  if (isLoading) return <SectionSkeleton className="h-96" />;
  if (isError || !layout) return <SectionError onRetry={() => refetch()} message={t("errLoadFailed")} />;

  const canAdmit = can("manage_admissions");
  const canViewResident = can("view_resident_profile");

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-bold text-ink">{layout.property.name}</h1>
        <MonthNavigator value={period} onChange={setPeriod} />
      </div>

      {/* Stats strip */}
      <div className="grid grid-cols-5 gap-2 rounded-2xl border border-border bg-surface-card p-4 text-center">
        <Stat label={t("statsTotal")} value={layout.counts.total} />
        <Stat label={t("statsOccupied")} value={layout.counts.occupied} tone="accent" />
        <Stat label={t("statsAvailable")} value={layout.counts.available} tone="good" />
        <Stat label={t("statsReserved")} value={layout.counts.reserved} tone="warn" />
        <Stat label={t("statsMaintenance")} value={layout.counts.maintenance} />
      </div>
      {layout.counts.occupancy_rate === null && (
        <p className="text-center text-xs text-ink-muted">
          {layout.counts.total === 0 ? t("noBedsYet") : t("allUnderMaintenance")}
        </p>
      )}

      {/* Dues banner */}
      {layout.finance && (
        <Link
          href={`/billing?property=${propertyId}&status=outstanding`}
          className="flex items-center justify-between rounded-2xl border border-status-critical/20 bg-status-critical-soft px-5 py-3.5 text-sm transition-colors hover:bg-status-critical/10"
        >
          <span className="flex items-center gap-2 font-semibold text-status-critical">
            <AlertCircle className="size-4" />
            {Number(layout.finance.outstanding_total) > 0
              ? t("duesBanner", {
                  amount: layout.finance.outstanding_total,
                  count: layout.finance.residents_with_balance_count,
                })
              : t("duesBannerZero")}
          </span>
          <MoneyText value={layout.finance.outstanding_total} className="font-bold text-status-critical" />
        </Link>
      )}

      {/* Building tabs */}
      {layout.buildings.length > 1 && (
        <div className="flex gap-2 overflow-x-auto">
          {layout.buildings.map((b) => (
            <button
              key={b.id}
              type="button"
              onClick={() => {
                setBuildingId(b.id);
                setFloorId(null);
              }}
              className={`shrink-0 rounded-full px-4 py-1.5 text-xs font-semibold transition-colors cursor-pointer ${
                activeBuilding?.id === b.id ? "bg-surface-inverse text-ink-inverse" : "border border-border text-ink-muted"
              }`}
            >
              {b.name} ({b.counts.total})
            </button>
          ))}
        </div>
      )}

      {/* Floor tabs */}
      {activeBuilding && activeBuilding.floors.length > 1 && (
        <div className="flex gap-2 overflow-x-auto">
          {activeBuilding.floors.map((f) => (
            <button
              key={f.id}
              type="button"
              onClick={() => setFloorId(f.id)}
              className={`shrink-0 rounded-full px-4 py-1.5 text-xs font-semibold transition-colors cursor-pointer ${
                activeFloor?.id === f.id ? "bg-accent text-ink-inverse" : "border border-border text-ink-muted"
              }`}
            >
              {f.name} ({f.counts.total})
            </button>
          ))}
        </div>
      )}

      {/* Filters */}
      <div className="flex gap-2 overflow-x-auto">
        {BED_FILTERS.map((f) => (
          <button
            key={f}
            type="button"
            onClick={() => setFilter(f)}
            className={`shrink-0 rounded-full px-3 py-1 text-xs font-semibold transition-colors cursor-pointer ${
              filter === f ? "bg-ink text-ink-inverse" : "border border-border text-ink-muted"
            }`}
          >
            {t(`filter${f[0].toUpperCase()}${f.slice(1)}` as "filterAll" | "filterAvailable" | "filterWithBalance" | "filterOnNotice")}
          </button>
        ))}
      </div>

      {/* Rooms */}
      <div className="space-y-4">
        {activeFloor?.rooms.map((room: LayoutRoom) => (
          <div key={room.id} className="rounded-2xl border border-border bg-surface-card p-4">
            <div className="mb-3 flex items-center justify-between">
              <Link
                href={`/properties/${propertyId}/floors/${activeFloor.id}/rooms`}
                className="flex items-center gap-1.5 text-sm font-bold text-ink hover:text-accent"
              >
                <BedDouble className="size-4" />
                {room.room_number}
              </Link>
              <span className="text-xs text-ink-muted">
                {room.counts.occupied}/{room.counts.total}
              </span>
            </div>
            <div className="grid grid-cols-4 gap-2 sm:grid-cols-6 md:grid-cols-8">
              {room.beds
                .filter((bed) => bedMatchesFilter(bed, filter))
                .map((bed) => {
                  const canAct =
                    bed.availability === "available" ? canAdmit : bed.resident ? canViewResident : false;
                  const href =
                    bed.availability === "available"
                      ? `/admissions?property=${propertyId}&room=${room.id}&bed=${bed.id}`
                      : bed.resident
                        ? `/residents/${bed.resident.id}`
                        : undefined;
                  return <BedTile key={bed.id} bed={bed} canAct={canAct} href={href} />;
                })}
            </div>
          </div>
        ))}
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-4 rounded-2xl border border-border bg-surface-card p-4 text-xs text-ink-muted">
        <LegendSwatch className="border-border bg-surface-card" label={t("legendAvailable")} />
        <LegendSwatch className="border-accent/30 bg-accent-soft" label={t("legendOccupied")} />
        <LegendSwatch className="border-status-warn/30 bg-status-warn-soft" label={t("legendReserved")} />
        <LegendSwatch className="border-border bg-surface-subtle" label={t("legendMaintenance")} />
        <LegendDot className="bg-status-good" label={t("legendPaid")} />
        <LegendDot className="bg-status-warn" label={t("legendDue")} />
        <LegendDot className="bg-status-critical" label={t("legendOverdue")} />
        <span className="flex items-center gap-1.5">
          <AlertCircle className="size-3 text-status-warn" />
          {t("legendOnNotice")}
        </span>
      </div>
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: "accent" | "good" | "warn" }) {
  const toneClass =
    tone === "accent" ? "text-accent" : tone === "good" ? "text-status-good" : tone === "warn" ? "text-status-warn" : "text-ink";
  return (
    <div>
      <p className="text-[10px] uppercase text-ink-faint">{label}</p>
      <p className={`text-lg font-bold ${toneClass}`}>{value}</p>
    </div>
  );
}

function LegendSwatch({ className, label }: { className: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={`size-3 rounded border ${className}`} aria-hidden />
      {label}
    </span>
  );
}

function LegendDot({ className, label }: { className: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={`size-1.5 rounded-full ${className}`} aria-hidden />
      {label}
    </span>
  );
}
