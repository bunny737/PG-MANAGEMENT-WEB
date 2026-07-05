import { cn } from "@/lib/utils";

interface StatusPillProps {
  label: string;
  tone?: "critical" | "neutral";
  className?: string;
}

/** Status colour always ships with a text label — never colour alone. */
export function StatusPill({
  label,
  tone = "neutral",
  className,
}: StatusPillProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium",
        tone === "critical"
          ? "bg-status-critical-soft text-status-critical"
          : "bg-border text-ink-muted",
        className
      )}
    >
      {label}
    </span>
  );
}
