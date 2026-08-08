import { BedDouble } from "lucide-react";
import Link from "next/link";
import { ProgressBar } from "@/components/shared/ProgressBar";
import { StatTile } from "@/components/shared/StatTile";
import type { OccupancySummary } from "./types";

export function OccupancyCard({ data }: { data: OccupancySummary }) {
  return (
    <section className="flex h-full flex-col justify-between rounded-2xl border border-border bg-surface-card p-5.5 shadow-xs transition-all hover:border-border-strong hover:shadow-md">
      <div>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="flex items-center gap-2.5 font-display text-base font-bold text-ink">
            <span className="flex size-8.5 items-center justify-center rounded-xl bg-accent-soft text-accent ring-1 ring-accent/15">
              <BedDouble className="size-4.5" aria-hidden />
            </span>
            Occupancy Status
          </h2>
          <Link
            href="/properties"
            className="text-xs font-semibold tracking-wide text-accent transition-colors hover:text-accent-hover hover:underline"
          >
            View Details ›
          </Link>
        </div>

        <div className="grid grid-cols-3 gap-3">
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
      </div>

      <div className="mt-5 pt-3 border-t border-border/60">
        <div className="mb-2 flex items-center justify-between text-xs font-medium text-ink-muted">
          <span>Capacity Filled</span>
          <span className="font-semibold text-ink">{data.occupiedBeds} of {data.totalBeds} beds ({data.occupiedPercent}%)</span>
        </div>
        <ProgressBar percent={data.occupiedPercent} label="Beds occupied" />
      </div>
    </section>
  );
}
