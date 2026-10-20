import { cn } from "@/lib/utils";

export type SummaryTone = "good" | "warn" | "total" | "neutral";

const TONES: Record<SummaryTone, string> = {
  good: "bg-m3-good-container text-m3-good",
  warn: "bg-m3-warn-container text-m3-warn",
  total: "bg-m3-total-container text-m3-total",
  neutral: "bg-m3-surface-container-high text-m3-on-surface-variant",
};

interface SummaryTileProps {
  value: React.ReactNode;
  label: string;
  tone?: SummaryTone;
  icon?: React.ReactNode;
  sublabel?: string;
  className?: string;
}

/** Tonal count tile ("5 Vacant Beds"): big number, label under it, optional leading icon. */
export function SummaryTile({ value, label, tone = "neutral", icon, sublabel, className }: SummaryTileProps) {
  return (
    <div className={cn("flex items-center gap-3 rounded-2xl px-4 py-4", TONES[tone], className)}>
      {icon && (
        <span aria-hidden className="flex size-7 shrink-0 items-center justify-center">
          {icon}
        </span>
      )}
      <div className="min-w-0">
        <p className="text-[28px] leading-8 font-bold">{value}</p>
        {sublabel && <p className="text-sm leading-4 font-medium">{sublabel}</p>}
        <p className="text-base leading-6 font-medium">{label}</p>
      </div>
    </div>
  );
}
