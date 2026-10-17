import { formatMoney } from "@/lib/money";
import { cn } from "@/lib/utils";

interface MoneyTextProps {
  /** A Decimal string from the API, or null/undefined for a redacted field. */
  value: string | null | undefined;
  className?: string;
  /** Marks a figure that needs attention (e.g. overdue) via colour only —
   * never strikethrough, which would misread as "waived" (invariant F1 note
   * on MoneyStat). */
  attention?: boolean;
}

/** Renders an API money string with tabular numerals, invariant F1's
 * single rendering path — nothing else in the app should call
 * `formatMoney` directly inside JSX. */
export function MoneyText({ value, className, attention }: MoneyTextProps) {
  return (
    <span
      className={cn("tabular-nums", attention && "font-bold text-status-critical", className)}
    >
      {formatMoney(value)}
    </span>
  );
}
