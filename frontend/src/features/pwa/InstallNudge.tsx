"use client";

import { useState } from "react";
import { usePathname } from "next/navigation";
import { Download, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { IosInstallDialog } from "./IosInstallDialog";
import { useInstall } from "./useInstall";

const DISMISSED_KEY = "installNudgeDismissed";

function readDismissed() {
  try {
    return localStorage.getItem(DISMISSED_KEY) === "1";
  } catch {
    return false;
  }
}

/** One-time prompt on the dashboard to install the app. Dismissing it is remembered on this
 * device; the always-available entry is the InstallCard on the More screen. Not cleared on
 * logout on purpose: it is a device preference, not tenant data. */
export function InstallNudge() {
  const t = useTranslations("pwa.install");
  const pathname = usePathname();
  const { state, install } = useInstall();
  const [dismissed, setDismissed] = useState(readDismissed);
  const [iosOpen, setIosOpen] = useState(false);

  if (pathname !== "/dashboard" || dismissed || state === "installed" || state === "unsupported") return null;

  const dismiss = () => {
    try {
      localStorage.setItem(DISMISSED_KEY, "1");
    } catch {
      // Private mode: it just comes back next visit.
    }
    setDismissed(true);
  };

  return (
    <>
      <div className="mx-4 mt-3 flex items-center gap-3 rounded-xl border border-accent-border bg-accent-soft px-3 py-2.5 md:hidden">
        <Download className="size-4 shrink-0 text-accent" aria-hidden />
        <p className="min-w-0 flex-1 text-xs font-medium text-ink">{t("description")}</p>
        <button
          type="button"
          onClick={() => (state === "installable" ? void install() : setIosOpen(true))}
          className="shrink-0 cursor-pointer rounded-lg bg-accent px-3 py-1.5 text-xs font-semibold text-ink-inverse transition-colors hover:bg-accent-hover"
        >
          {t("action")}
        </button>
        <button
          type="button"
          onClick={dismiss}
          aria-label={t("dismiss")}
          className="shrink-0 cursor-pointer rounded-lg p-1 text-ink-muted transition-colors hover:text-ink"
        >
          <X className="size-4" aria-hidden />
        </button>
      </div>
      <IosInstallDialog open={iosOpen} onClose={() => setIosOpen(false)} inApp={state === "ios-in-app"} />
    </>
  );
}
