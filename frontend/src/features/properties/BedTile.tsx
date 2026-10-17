"use client";

import Link from "next/link";
import { AlertCircle } from "lucide-react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import type { LayoutBed } from "@/lib/api";

const AVAILABILITY_STYLES: Record<LayoutBed["availability"], string> = {
  available: "border-border bg-surface-card text-ink-muted",
  occupied: "border-accent/30 bg-accent-soft text-accent",
  reserved: "border-status-warn/30 bg-status-warn-soft text-status-warn",
  maintenance: "border-border bg-surface-subtle text-ink-faint",
};

const PAYMENT_DOT_STYLES: Record<string, string> = {
  paid: "bg-status-good",
  upcoming: "bg-ink-faint",
  due: "bg-status-warn",
  overdue: "bg-status-critical",
  no_invoice: "bg-ink-faint",
};

interface BedTileProps {
  bed: LayoutBed;
  /** Whether the viewer may act on this tile (manage_admissions for an
   * available bed, view_resident_profile for an occupied one) — without it,
   * the tile is visibly non-interactive (F8). */
  canAct: boolean;
  href?: string;
}

/** One bed in the D2 grid. Three independent signals, never colour alone:
 * the fill shows availability, a dot shows payment status, a badge shows
 * notice — each is also named in the accessible label. */
export function BedTile({ bed, canAct, href }: BedTileProps) {
  const t = useTranslations("properties.layout");
  const tStatus = useTranslations("status");

  const residentName = bed.resident ? bed.resident.name : null;
  const label = bed.resident
    ? residentName ?? t("occupiedRedacted")
    : tStatus(bed.availability);

  const content = (
    <div
      className={cn(
        "relative flex aspect-square flex-col items-center justify-center gap-0.5 rounded-xl border p-1.5 text-center transition-all",
        AVAILABILITY_STYLES[bed.availability],
        canAct ? "cursor-pointer hover:shadow-md hover:-translate-y-0.5" : "cursor-default opacity-90"
      )}
      role={canAct ? "button" : undefined}
      aria-label={`${bed.bed_number}: ${label}`}
    >
      {bed.resident?.on_notice && (
        <AlertCircle className="absolute -top-1.5 -right-1.5 size-3.5 rounded-full bg-surface-card text-status-warn" aria-label={t("onNotice")} />
      )}
      {bed.payment && (
        <span
          className={cn("absolute top-1 left-1 size-1.5 rounded-full", PAYMENT_DOT_STYLES[bed.payment.status])}
          aria-hidden
        />
      )}
      <span className="text-[10px] font-bold">{bed.bed_number}</span>
      {bed.resident && <span className="line-clamp-1 w-full text-[9px] leading-tight">{label}</span>}
    </div>
  );

  if (canAct && href) {
    return (
      <Link href={href} className="block">
        {content}
      </Link>
    );
  }
  return content;
}
