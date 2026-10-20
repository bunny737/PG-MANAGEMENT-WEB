"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import "@/lib/pwa"; // starts listening for beforeinstallprompt as early as possible

/** Registers the service worker (public/sw.js, built from app/sw.ts) and offers a Reload
 * when a new version is waiting. Installed PWAs stay alive for days (iOS especially), so the
 * worker is also re-checked every time the app returns to the foreground. */
export function PwaRegister() {
  const t = useTranslations("pwa.update");
  const [waiting, setWaiting] = useState<ServiceWorker | null>(null);
  const reloadRequested = useRef(false);

  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;

    if (process.env.NODE_ENV !== "production") {
      // The worker is not built in dev; drop one left behind by a production build on this origin.
      void navigator.serviceWorker.getRegistrations().then((all) => all.forEach((r) => void r.unregister()));
      return;
    }

    let registration: ServiceWorkerRegistration | undefined;
    const onVisible = () => {
      if (document.visibilityState === "visible") void registration?.update().catch(() => {});
    };
    // clientsClaim fires controllerchange on the very first install too; only reload when the
    // user asked for an update.
    const onControllerChange = () => {
      if (reloadRequested.current) window.location.reload();
    };

    void navigator.serviceWorker
      .register("/sw.js", { scope: "/" })
      .then((reg) => {
        registration = reg;
        if (reg.waiting && navigator.serviceWorker.controller) setWaiting(reg.waiting);
        reg.addEventListener("updatefound", () => {
          const installing = reg.installing;
          installing?.addEventListener("statechange", () => {
            if (installing.state === "installed" && navigator.serviceWorker.controller) setWaiting(installing);
          });
        });
      })
      .catch(() => {
        // Registration failing only costs offline support; the app itself is unaffected.
      });

    document.addEventListener("visibilitychange", onVisible);
    navigator.serviceWorker.addEventListener("controllerchange", onControllerChange);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      navigator.serviceWorker.removeEventListener("controllerchange", onControllerChange);
    };
  }, []);

  if (!waiting) return null;

  return (
    <div
      role="status"
      className="fixed inset-x-4 bottom-[calc(5rem+env(safe-area-inset-bottom)+var(--fab-stack,0px))] z-50 flex items-center justify-between gap-3 rounded-xl bg-surface-inverse px-4 py-3 text-sm text-ink-inverse shadow-lg md:inset-x-auto md:right-4 md:bottom-4 md:w-96"
    >
      <span>{t("available")}</span>
      <button
        type="button"
        onClick={() => {
          reloadRequested.current = true;
          waiting.postMessage({ type: "SKIP_WAITING" });
        }}
        className="shrink-0 cursor-pointer rounded-lg bg-accent px-3 py-1.5 text-xs font-semibold text-ink-inverse transition-colors hover:bg-accent-hover"
      >
        {t("reload")}
      </button>
    </div>
  );
}
