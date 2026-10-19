"use client";

import { onlineManager } from "@tanstack/react-query";
import { WifiOff } from "lucide-react";
import { useTranslations } from "next-intl";
import { useSyncExternalStore } from "react";

const subscribe = (callback: () => void) => onlineManager.subscribe(callback);
const getOnline = () => onlineManager.isOnline();

/** Persistent notice while the device is offline (docs/frontend-plan.md §5.1: offline is
 * read-only). Follows TanStack Query's online state so it matches when queries pause. */
export function OfflineBanner() {
  const t = useTranslations("pwa.offline");
  const online = useSyncExternalStore(subscribe, getOnline, () => true);
  if (online) return null;

  return (
    <div
      role="status"
      className="sticky top-0 z-30 flex items-center gap-2 bg-status-warn-soft px-4 py-2 text-xs font-medium text-status-warn"
    >
      <WifiOff className="size-4 shrink-0" aria-hidden />
      <span>{t("banner")}</span>
    </div>
  );
}
