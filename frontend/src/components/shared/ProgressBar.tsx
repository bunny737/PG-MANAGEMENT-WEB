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
      className="h-2.5 w-full overflow-hidden rounded-full bg-border shadow-[inset_0_1px_2px_rgb(11_18_32/0.08)]"
    >
      {/* Gradient reads as one accent hue with a highlight, not two data
          categories — the fill is still a single measure. */}
      <div
        className="h-full rounded-full bg-linear-to-r from-accent to-accent-hover transition-[width] duration-500 ease-out"
        style={{ width: `${clamped}%` }}
      />
    </div>
  );
}
