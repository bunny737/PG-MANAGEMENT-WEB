import { Fragment } from "react";
import { Banknote, UserPlus, UserRound } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ActivityItem } from "./types";

// Icon/tint mapped from the semantic `tone`, not a hardcoded per-item choice
// — keeps the activity feed on the same restrained palette as the rest of
// the dashboard (accent/good/neutral) rather than adding a one-off hue.
const TONE_STYLES: Record<
  ActivityItem["tone"],
  { icon: typeof UserPlus; iconBg: string; iconColor: string }
> = {
  info: { icon: UserPlus, iconBg: "bg-accent-soft", iconColor: "text-accent" },
  good: { icon: Banknote, iconBg: "bg-status-good-soft", iconColor: "text-status-good" },
  neutral: { icon: UserRound, iconBg: "bg-border", iconColor: "text-ink-muted" },
};

/** Splits "...**bold**..." into text/strong segments — the mock data marks
 * emphasis (resident name, etc.) the same way a CMS/API field might. */
function renderEmphasis(text: string) {
  return text.split(/\*\*(.+?)\*\*/g).map((segment, index) =>
    index % 2 === 1 ? (
      <strong key={index} className="font-semibold text-ink">
        {segment}
      </strong>
    ) : (
      <Fragment key={index}>{segment}</Fragment>
    )
  );
}

export function TodaysActivity({ items }: { items: ActivityItem[] }) {
  return (
    <section className="rounded-2xl bg-surface-card p-5 shadow-sm">
      <h2 className="mb-4 text-base font-bold text-ink">Today&apos;s Activity</h2>

      <ul className="flex flex-col gap-4">
        {items.map((item) => {
          const { icon: Icon, iconBg, iconColor } = TONE_STYLES[item.tone];
          return (
            <li key={item.id} className="flex items-start gap-3">
              <span
                className={cn(
                  "flex size-9 shrink-0 items-center justify-center rounded-full",
                  iconBg
                )}
              >
                <Icon className={cn("size-4", iconColor)} aria-hidden />
              </span>
              <div className="flex flex-col gap-0.5">
                <p className="text-sm text-ink-muted">
                  {renderEmphasis(item.text)}
                </p>
                <span className="text-xs text-ink-faint">{item.timestamp}</span>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
