"use client";

import { Fragment } from "react";
import {
  Banknote,
  Clock,
  UserPlus,
  Wifi,
  Wrench,
  AlertCircle
} from "lucide-react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import type { ActivityItem } from "./types";

/** Dynamically determines the appropriate icon and color scheme based on activity content */
function getActivityIconConfig(item: ActivityItem) {
  const text = item.text.toLowerCase();
  
  if (text.includes("wifi") || text.includes("internet")) {
    return {
      icon: Wifi,
      iconBg: "bg-indigo-500/10 ring-1 ring-indigo-500/20",
      iconColor: "text-indigo-600 dark:text-indigo-400"
    };
  }
  if (text.includes("complaint") || text.includes("electrical") || text.includes("leak") || text.includes("air conditioner") || text.includes("water")) {
    return {
      icon: Wrench,
      iconBg: "bg-amber-500/10 ring-1 ring-amber-500/20",
      iconColor: "text-amber-600 dark:text-amber-400"
    };
  }
  if (item.tone === "good" || text.includes("payment") || text.includes("rent")) {
    return {
      icon: Banknote,
      iconBg: "bg-emerald-500/10 ring-1 ring-emerald-500/20",
      iconColor: "text-emerald-600 dark:text-emerald-400"
    };
  }
  if (item.tone === "info" || text.includes("resident") || text.includes("checked")) {
    return {
      icon: UserPlus,
      iconBg: "bg-accent-soft ring-1 ring-accent/20",
      iconColor: "text-accent"
    };
  }
  return {
    icon: AlertCircle,
    iconBg: "bg-surface-subtle ring-1 ring-border",
    iconColor: "text-ink-muted"
  };
}

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
  const t = useTranslations("dashboard.activity");

  return (
    <section className="flex h-full flex-col justify-between rounded-2xl border border-border bg-surface-card p-5.5 shadow-xs transition-all hover:border-border-strong hover:shadow-md">
      <div>
        <h2 className="mb-4 flex items-center gap-2.5 font-display text-base font-bold text-ink">
          <span className="flex size-8.5 items-center justify-center rounded-xl bg-surface-subtle text-ink-muted ring-1 ring-border">
            <Clock className="size-4.5" aria-hidden />
          </span>
          {t("title")}
        </h2>

        {items.length > 0 ? (
          <ul className="relative flex flex-col gap-4.5">
            <span
              className="absolute top-2 bottom-2 left-4.5 w-px -translate-x-1/2 bg-border/80"
              aria-hidden
            />
            {items.map((item) => {
              const { icon: Icon, iconBg, iconColor } = getActivityIconConfig(item);
              return (
                <li key={item.id} className="relative flex items-start gap-3.5">
                  <span
                    className={cn(
                      "relative z-10 flex size-9 shrink-0 items-center justify-center rounded-full bg-surface-card ring-4 ring-surface-card",
                      iconBg
                    )}
                  >
                    <Icon className={cn("size-4", iconColor)} aria-hidden />
                  </span>
                  <div className="flex flex-col gap-0.5 pt-1">
                    <p className="text-xs leading-relaxed text-ink-muted">
                      {renderEmphasis(item.text)}
                    </p>
                    <span className="text-[0.6875rem] font-semibold text-ink-faint">
                      {item.timestamp}
                    </span>
                  </div>
                </li>
              );
            })}
          </ul>
        ) : (
          <div className="rounded-xl bg-surface-subtle px-4 py-8 text-center text-xs font-medium text-ink-muted">
            {t("noActivity")}
          </div>
        )}
      </div>
    </section>
  );
}
