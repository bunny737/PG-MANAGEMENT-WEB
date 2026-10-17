"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { useLocale } from "next-intl";
import { addMonths, currentMonthKey, formatMonthLabel } from "@/lib/period";
import { cn } from "@/lib/utils";

interface MonthNavigatorProps {
  /** "YYYY-MM"; defaults to the current month if omitted. */
  value: string;
  onChange: (monthKey: string) => void;
  className?: string;
  /** Disables the forward arrow past the current month — most of this
   * roadmap's screens show "to date" figures, not a future projection. */
  disableFuture?: boolean;
}

export function MonthNavigator({ value, onChange, className, disableFuture = true }: MonthNavigatorProps) {
  const locale = useLocale();
  const isCurrentOrFuture = disableFuture && value >= currentMonthKey();

  return (
    <div className={cn("inline-flex items-center gap-1 rounded-xl border border-border bg-surface-card p-1", className)}>
      <button
        type="button"
        onClick={() => onChange(addMonths(value, -1))}
        className="flex size-8 items-center justify-center rounded-lg text-ink-muted transition-colors hover:bg-surface-subtle hover:text-ink cursor-pointer"
        aria-label="Previous month"
      >
        <ChevronLeft className="size-4" />
      </button>
      <span className="min-w-[8rem] text-center text-sm font-semibold text-ink tabular-nums">
        {formatMonthLabel(value, locale)}
      </span>
      <button
        type="button"
        onClick={() => onChange(addMonths(value, 1))}
        disabled={isCurrentOrFuture}
        className="flex size-8 items-center justify-center rounded-lg text-ink-muted transition-colors hover:bg-surface-subtle hover:text-ink disabled:cursor-not-allowed disabled:opacity-30 cursor-pointer"
        aria-label="Next month"
      >
        <ChevronRight className="size-4" />
      </button>
    </div>
  );
}
