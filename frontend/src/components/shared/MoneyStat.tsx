import { TrendingDown, TrendingUp } from "lucide-react";
import { cn } from "@/lib/utils";

interface MoneyStatProps {
  label: string;
  /** Pre-formatted money string from the API (invariant F1 — never do
   * arithmetic on money client-side; this component only renders). */
  amount: string;
  delta?: { direction: "up" | "down"; label: string };
  inverse?: boolean;
  className?: string;
}

export function MoneyStat({
  label,
  amount,
  delta,
  inverse,
  className,
}: MoneyStatProps) {
  const DeltaIcon = delta?.direction === "down" ? TrendingDown : TrendingUp;
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <span
        className={cn(
          "text-xs font-medium tracking-wide uppercase",
          inverse ? "text-ink-inverse-muted" : "text-ink-faint"
        )}
      >
        {label}
      </span>
      <span
        className={cn(
          "text-3xl font-bold tabular-nums",
          inverse ? "text-ink-inverse" : "text-ink"
        )}
      >
        {amount}
      </span>
      {delta ? (
        <span
          className={cn(
            "flex items-center gap-1 text-sm font-medium",
            delta.direction === "down"
              ? "text-status-critical"
              : "text-status-good"
          )}
        >
          <DeltaIcon className="size-4" aria-hidden />
          {delta.label}
        </span>
      ) : null}
    </div>
  );
}

interface MoneyRowProps {
  label: string;
  amount: string;
  emphasis?: boolean;
  attention?: boolean;
}

/** A label/amount row inside the Financials card. `attention` marks a figure
 * that needs the owner's notice (e.g. outstanding dues) via colour only —
 * never strikethrough, which would misread as "waived". */
export function MoneyRow({ label, amount, emphasis, attention }: MoneyRowProps) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-ink-inverse-muted">{label}</span>
      <span
        className={cn(
          "tabular-nums",
          emphasis ? "text-base font-semibold text-ink-inverse" : "text-ink-inverse",
          attention && "font-semibold text-status-critical"
        )}
      >
        {amount}
      </span>
    </div>
  );
}
