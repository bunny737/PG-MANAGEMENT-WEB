"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { PropertyFilter } from "@/components/shared/PropertyFilter";
import { cn } from "@/lib/utils";
import { FoodHolidaysList } from "./FoodHolidaysList";
import { NoticesList } from "./NoticesList";

const TABS = ["notices", "holidays"] as const;
type Tab = (typeof TABS)[number];

/** The /notices shell. The active tab lives in the URL (`?tab=`), so a link from a food holiday or a
 * bookmark opens the right one; `?notice=<id>` deep-links a notice on the first tab. */
export function NoticesTabs() {
  const t = useTranslations("notices");
  const router = useRouter();
  const searchParams = useSearchParams();
  const requested = searchParams.get("tab");
  const activeTab: Tab = requested === "holidays" ? "holidays" : "notices";

  function setTab(tab: Tab) {
    const params = new URLSearchParams(searchParams);
    params.set("tab", tab);
    params.delete("notice");
    router.push(`/notices?${params.toString()}`);
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-ink md:text-3xl">{t("title")}</h1>
          <p className="mt-1 text-sm text-ink-muted">{t("subtitle")}</p>
        </div>
        <PropertyFilter />
      </div>

      <div className="flex gap-2 overflow-x-auto border-b border-border">
        {TABS.map((tab) => (
          <button
            key={tab}
            type="button"
            onClick={() => setTab(tab)}
            className={cn(
              "shrink-0 border-b-2 px-3 py-2.5 text-sm font-semibold transition-colors cursor-pointer",
              activeTab === tab ? "border-accent text-accent" : "border-transparent text-ink-muted hover:text-ink"
            )}
          >
            {t(`tabs.${tab}`)}
          </button>
        ))}
      </div>

      {activeTab === "notices" && <NoticesList />}
      {activeTab === "holidays" && <FoodHolidaysList />}
    </div>
  );
}
