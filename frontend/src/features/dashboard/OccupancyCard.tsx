"use client";

import { BedDouble } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { ProgressBar } from "@/components/shared/ProgressBar";
import { StatTile } from "@/components/shared/StatTile";
import type { OccupancySummary } from "./types";

export function OccupancyCard({ data }: { data: OccupancySummary }) {
  const t = useTranslations("dashboard.occupancy");

  return (
    <section className="flex h-full flex-col justify-between rounded-2xl border border-border bg-surface-card p-5.5 shadow-xs transition-all hover:border-border-strong hover:shadow-md">
      <div>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="flex items-center gap-2.5 font-display text-base font-bold text-ink">
            <span className="flex size-8.5 items-center justify-center rounded-xl bg-accent-soft text-accent ring-1 ring-accent/15">
              <BedDouble className="size-4.5" aria-hidden />
            </span>
            {t("title")}
          </h2>
          <Link
            href="/properties"
            className="text-xs font-semibold tracking-wide text-accent transition-colors hover:text-accent-hover hover:underline"
          >
            {t("viewDetails")}
          </Link>
        </div>

        <div className="grid grid-cols-3 gap-3">
          <StatTile label={t("totalBeds")} value={String(data.totalBeds)} />
          <StatTile
            label={t("occupied")}
            value={String(data.occupiedBeds)}
            sublabel={`${data.occupiedPercent}%`}
            tone="accent"
            dot="accent"
          />
          <StatTile
            label={t("vacant")}
            value={String(data.vacantBeds)}
            sublabel={`${data.vacantPercent}%`}
            dot="neutral"
          />
        </div>
      </div>

      <div className="mt-5 pt-3 border-t border-border/60">
        <div className="mb-2 flex items-center justify-between text-xs font-medium text-ink-muted">
          <span>{t("capacityFilled")}</span>
          <span className="font-semibold text-ink">
            {t("capacitySubtitle", { occupied: data.occupiedBeds, total: data.totalBeds, percent: data.occupiedPercent })}
          </span>
        </div>
        <ProgressBar percent={data.occupiedPercent} label={t("bedsOccupied")} />
      </div>
    </section>
  );
}
