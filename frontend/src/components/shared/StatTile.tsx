import { cn } from "@/lib/utils";

interface StatTileProps {
  label: string;
  value: string;
  sublabel?: string;
  tone?: "default" | "accent";
  /** Small dot before the label — marks which slice of a whole this stat
   * represents (e.g. occupied vs vacant beds). Always paired with the label
   * text, never color alone. */
  dot?: "accent" | "neutral";
  className?: string;
}

/** A bordered mini-panel: uppercase faint label + bold tabular number +
 * optional muted sub-line. The panel (rather than bare text) keeps a row of
 * tiles reading as one unit of comparable figures. */
export function StatTile({
  label,
  value,
  sublabel,
  tone = "default",
  dot,
  className,
}: StatTileProps) {
  const isAccent = tone === "accent";
  return (
    <div
      className={cn(
        "flex flex-col gap-1 rounded-xl border px-3 py-2.5",
        isAccent
          ? "border-accent-border bg-accent-soft"
          : "border-border bg-surface-subtle",
        className
      )}
    >
      <span
        className={cn(
          "flex items-center gap-1.5 text-[0.6875rem] font-semibold tracking-[0.06em] uppercase",
          isAccent ? "text-accent" : "text-ink-faint"
        )}
      >
        {dot ? (
          <span
            className={cn(
              "size-1.5 shrink-0 rounded-full",
              dot === "accent" ? "bg-accent" : "bg-ink-faint"
            )}
            aria-hidden
          />
        ) : null}
        {label}
      </span>
      <span
        className={cn(
          "font-display text-3xl leading-none font-bold tabular-nums",
          isAccent ? "text-accent" : "text-ink"
        )}
      >
        {value}
      </span>
      {sublabel ? (
        <span
          className={cn(
            "text-xs font-medium tabular-nums",
            isAccent ? "text-accent/70" : "text-ink-faint"
          )}
        >
          {sublabel}
        </span>
      ) : null}
    </div>
  );
}
