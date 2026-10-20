"use client";

import { onlineManager } from "@tanstack/react-query";
import { WifiOff } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useSyncExternalStore } from "react";

const subscribe = (callback: () => void) => onlineManager.subscribe(callback);
const getOnline = () => onlineManager.isOnline();

/** Persistent notice while the device is offline (docs/frontend-plan.md §5.1: offline is
 * read-only). Follows TanStack Query's online state so it matches when queries pause. */
export function OfflineBanner() {
  const t = useTranslations("pwa.offline");
  const online = useSyncExternalStore(subscribe, getOnline, () => true);
  const ref = useRef<HTMLDivElement>(null);

  // The phone top bar is sticky too, so publish this banner's real height (it wraps to two or three lines
  // on a narrow screen, longer in Telugu) and the bar sits just below it. See MobileTopBar.
  useEffect(() => {
    const banner = ref.current;
    if (online || !banner) return;
    const root = document.documentElement;
    const publish = () => root.style.setProperty("--banner-h", `${banner.offsetHeight}px`);
    publish();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(publish);
    observer?.observe(banner);
    return () => {
      observer?.disconnect();
      root.style.removeProperty("--banner-h");
    };
  }, [online]);

  if (online) return null;

  return (
    <div
      ref={ref}
      role="status"
      className="sticky top-0 z-30 flex items-center gap-2 bg-status-warn-soft px-4 py-2 text-xs font-medium text-status-warn max-md:bg-m3-warn-container max-md:text-m3-warn"
    >
      <WifiOff className="size-4 shrink-0" aria-hidden />
      <span>{t("banner")}</span>
    </div>
  );
}
