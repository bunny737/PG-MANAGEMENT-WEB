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
  const isDown = delta?.direction === "down";
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <span
        className={cn(
          "text-[0.6875rem] font-semibold tracking-[0.06em] uppercase",
          inverse ? "text-ink-inverse-muted" : "text-ink-faint"
        )}
      >
        {label}
      </span>
      <span
        className={cn(
          "font-display text-[2.125rem] leading-none font-bold tabular-nums",
          inverse ? "text-ink-inverse" : "text-ink"
        )}
      >
        {amount}
      </span>
      {delta ? (
        <span
          className={cn(
            "inline-flex w-fit items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold tabular-nums",
            isDown
              ? "bg-status-critical/15 text-status-critical"
              : "bg-status-good/15 text-status-good",
            // On the dark card the -600 status inks lose contrast; lighten them.
            inverse && (isDown ? "text-red-300" : "text-emerald-300")
          )}
        >
          <DeltaIcon className="size-3.5" aria-hidden />
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
    <div className="flex items-center justify-between gap-3 rounded-lg px-2 py-1.5 text-sm transition-colors hover:bg-white/5">
      <span className="text-ink-inverse-muted">{label}</span>
      <span
        className={cn(
          "font-display tabular-nums",
          emphasis
            ? "text-base font-bold text-ink-inverse"
            : "font-semibold text-ink-inverse",
          // red-600 on near-black fails contrast — red-300 keeps the "needs
          // attention" read while staying legible.
          attention && "font-bold text-red-300"
        )}
      >
        {amount}
      </span>
    </div>
  );
}
