"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { X } from "lucide-react";
import { useTranslations } from "next-intl";
import { onForegroundPush, syncPush, type ForegroundPush } from "@/lib/push";
import { pushTargetUrl } from "@/lib/pushLinks";
import { usePushStatus } from "./usePushStatus";

const TOAST_MS = 8_000;

/** Mounted once in the signed-in shell. For a device that has opted in it refreshes the
 * registration on each start and shows pushes that arrive while the app is open (the browser
 * only displays them itself when the app is in the background). Renders nothing otherwise. */
export function PushRuntime() {
  const t = useTranslations("pwa.push");
  const router = useRouter();
  const status = usePushStatus();
  const [toast, setToast] = useState<ForegroundPush | null>(null);

  useEffect(() => {
    if (status !== "on") return;
    void syncPush();
    let stop: (() => void) | undefined;
    let cancelled = false;
    onForegroundPush(setToast)
      .then((unsubscribe) => {
        if (cancelled) unsubscribe();
        else stop = unsubscribe;
      })
      .catch(() => {});
    return () => {
      cancelled = true;
      stop?.();
    };
  }, [status]);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), TOAST_MS);
    return () => clearTimeout(timer);
  }, [toast]);

  if (!toast) return null;

  return (
    <div
      role="status"
      className="fixed inset-x-4 top-3 z-50 flex items-start gap-3 rounded-xl bg-surface-inverse px-4 py-3 text-ink-inverse shadow-lg md:inset-x-auto md:right-4 md:w-96"
    >
      <button
        type="button"
        className="min-w-0 flex-1 cursor-pointer text-start"
        onClick={() => {
          router.push(pushTargetUrl(toast.reference));
          setToast(null);
        }}
      >
        <p className="truncate text-sm font-semibold">{toast.title}</p>
        <p className="line-clamp-2 text-xs text-ink-inverse-muted">{toast.body}</p>
      </button>
      <button
        type="button"
        aria-label={t("close")}
        onClick={() => setToast(null)}
        className="shrink-0 cursor-pointer rounded-lg p-1 text-ink-inverse-muted transition-colors hover:text-ink-inverse"
      >
        <X className="size-4" aria-hidden />
      </button>
    </div>
  );
}
