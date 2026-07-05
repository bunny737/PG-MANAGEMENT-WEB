import { cn } from "@/lib/utils";

interface StatTileProps {
  label: string;
  value: string;
  sublabel?: string;
  tone?: "default" | "accent";
  className?: string;
}

/** Uppercase faint label + bold tabular number + optional muted sub-line. */
export function StatTile({
  label,
  value,
  sublabel,
  tone = "default",
  className,
}: StatTileProps) {
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <span
        className={cn(
          "text-xs font-medium tracking-wide uppercase",
          tone === "accent" ? "text-accent" : "text-ink-faint"
        )}
      >
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
