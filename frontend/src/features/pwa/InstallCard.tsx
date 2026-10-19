"use client";

import { useState } from "react";
import { Download } from "lucide-react";
import { useTranslations } from "next-intl";
import { IosInstallDialog } from "./IosInstallDialog";
import { useInstall } from "./useInstall";

/** "Install the app" row for the More screen. Renders nothing once installed or where the
 * browser can't install. */
export function InstallCard() {
  const t = useTranslations("pwa.install");
  const { state, install } = useInstall();
  const [iosOpen, setIosOpen] = useState(false);

  if (state === "installed" || state === "unsupported") return null;

  return (
    <>
      <div className="flex items-center gap-3 rounded-2xl border border-border bg-surface-card p-4 shadow-sm">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-accent-soft text-accent">
          <Download className="size-5" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-bold text-ink">{t("title")}</h3>
          <p className="text-xs text-ink-muted">{t("description")}</p>
        </div>
        <button
          type="button"
          onClick={() => (state === "installable" ? void install() : setIosOpen(true))}
          className="shrink-0 cursor-pointer rounded-xl bg-accent px-3 py-2 text-xs font-semibold text-ink-inverse transition-colors hover:bg-accent-hover"
        >
          {t("action")}
        </button>
      </div>
      <IosInstallDialog open={iosOpen} onClose={() => setIosOpen(false)} inApp={state === "ios-in-app"} />
    </>
  );
}
