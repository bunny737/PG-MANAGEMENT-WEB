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

/** Uppercase faint label + bold tabular number + optional muted sub-line. */
export function StatTile({
  label,
  value,
  sublabel,
  tone = "default",
  dot,
  className,
}: StatTileProps) {
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <span
        className={cn(
          "flex items-center gap-1.5 text-xs font-medium tracking-wide uppercase",
          tone === "accent" ? "text-accent" : "text-ink-faint"
        )}
      >
        {dot ? (
          <span
            className={cn(
              "size-1.5 rounded-full",
              dot === "accent" ? "bg-accent" : "bg-ink-faint"
            )}
            aria-hidden
          />
        ) : null}
        {label}
      </span>
      <span
        className={cn(
          "text-2xl font-bold tabular-nums",
          tone === "accent" ? "text-accent" : "text-ink"
        )}
      >
        {value}
      </span>
      {sublabel ? (
        <span className="text-xs text-ink-faint">{sublabel}</span>
      ) : null}
    </div>
  );
}
