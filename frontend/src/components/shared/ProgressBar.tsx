interface ProgressBarProps {
  /** 0–100. Single-hue accent fill on a border-colored track — a stat-tile
   * fill, not a categorical/multi-segment chart (no palette validation needed). */
  percent: number;
  label?: string;
}

export function ProgressBar({ percent, label }: ProgressBarProps) {
  const clamped = Math.min(100, Math.max(0, percent));
  return (
    <div
      role="progressbar"
      aria-valuenow={Math.round(clamped)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label}
      className="h-2 w-full overflow-hidden rounded-full bg-border"
    >
      <div
        className="h-full rounded-full bg-accent transition-[width]"
        style={{ width: `${clamped}%` }}
      />
    </div>
  );
}
