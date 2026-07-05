import { BedDouble } from "lucide-react";
import { ProgressBar } from "@/components/shared/ProgressBar";
import { StatTile } from "@/components/shared/StatTile";
import type { OccupancySummary } from "./types";

export function OccupancyCard({ data }: { data: OccupancySummary }) {
  return (
    <section className="rounded-2xl bg-surface-card p-5 shadow-sm">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-base font-bold text-ink">
          <BedDouble className="size-5 text-ink-muted" aria-hidden />
          Occupancy Status
        </h2>
        <a href="#" className="text-sm font-medium text-accent">
          Details ›
        </a>
      </div>

      <div className="mb-4 grid grid-cols-3 gap-2">
        <StatTile label="Total Beds" value={String(data.totalBeds)} />
        <StatTile
          label="Occupied"
          value={String(data.occupiedBeds)}
          sublabel={`${data.occupiedPercent}%`}
          tone="accent"
          dot="accent"
        />
        <StatTile
          label="Vacant"
          value={String(data.vacantBeds)}
          sublabel={`${data.vacantPercent}%`}
          dot="neutral"
        />
      </div>

      <ProgressBar percent={data.occupiedPercent} label="Beds occupied" />
    </section>
  );
}
