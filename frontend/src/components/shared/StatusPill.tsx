import { cn } from "@/lib/utils";

type Tone = "critical" | "warn" | "good" | "accent" | "neutral";

interface StatusPillProps {
  label: string;
  tone?: Tone;
  /** Leading dot. Redundant with the label — it only helps scanning a column
   * of pills, it never carries the meaning on its own. */
  dot?: boolean;
  className?: string;
}

const TONE_STYLES: Record<Tone, { pill: string; dot: string }> = {
  critical: {
    pill: "bg-status-critical-soft text-status-critical ring-status-critical/15",
    dot: "bg-status-critical",
  },
  warn: {
    pill: "bg-status-warn-soft text-status-warn ring-status-warn/15",
    dot: "bg-status-warn",
  },
  good: {
    pill: "bg-status-good-soft text-status-good ring-status-good/15",
    dot: "bg-status-good",
  },
  accent: {
    pill: "bg-accent-soft text-accent ring-accent/15",
    dot: "bg-accent",
  },
  neutral: {
    pill: "bg-surface-subtle text-ink-muted ring-border-strong/50",
    dot: "bg-ink-faint",
  },
};

/** Status colour always ships with a text label — never colour alone. */
export function StatusPill({
  label,
  tone = "neutral",
  dot = false,
  className,
}: StatusPillProps) {
  const styles = TONE_STYLES[tone];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset",
        styles.pill,
        className
      )}
    >
      {dot ? (
        <span
          className={cn("size-1.5 shrink-0 rounded-full", styles.dot)}
          aria-hidden
        />
      ) : null}
      {label}
    </span>
  );
}
