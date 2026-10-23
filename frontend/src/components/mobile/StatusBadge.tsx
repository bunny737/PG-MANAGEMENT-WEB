import { cn } from "@/lib/utils";

/**
 * Outlined, uppercase status badge as on the Android app. It has its own colour map and does not use
 * `getStatusTone`: the Android app shows inquiry in the tertiary (lavender) colour, while the desktop
 * pill maps it to warn.
 */
const STATUS_STYLES: Record<string, string> = {
  active: "border-[#5ca560] bg-[#e2ede5] text-[#2f5d33]",
  notice_period: "border-[#e79a2e] bg-[#fdecd2] text-[#7a4a00]",
  inquiry: "border-[#7e63c4] bg-m3-tertiary-container text-m3-on-tertiary-container",
  reserved: "border-[#7e63c4] bg-m3-tertiary-container text-m3-on-tertiary-container",
  vacated: "border-m3-outline-variant bg-m3-surface-container-high text-m3-on-surface-variant",
  absconded: "border-[#e57373] bg-m3-critical-container text-m3-critical",
  blacklisted: "border-[#e57373] bg-m3-critical-container text-m3-critical",
};

const FALLBACK = "border-m3-outline-variant bg-m3-surface-container-high text-m3-on-surface-variant";

export function statusBadgeStyle(status: string): string {
  return STATUS_STYLES[status] ?? FALLBACK;
}

interface StatusBadgeProps {
  status: string;
  /** Already-translated label (from the `status` namespace). */
  label: string;
  className?: string;
}

export function StatusBadge({ status, label, className }: StatusBadgeProps) {
  return (
    <span
      data-status={status}
      className={cn(
        "inline-flex shrink-0 items-center rounded-lg border px-3 py-2 text-xs leading-4 font-medium uppercase",
        statusBadgeStyle(status),
        className
      )}
    >
      {label}
    </span>
  );
}
