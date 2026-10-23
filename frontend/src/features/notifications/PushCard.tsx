"use client";

import { useState } from "react";
import { Bell, BellOff } from "lucide-react";
import { useTranslations } from "next-intl";
import { disablePush, enablePush } from "@/lib/push";
import { usePushStatus } from "./usePushStatus";

/** Notifications switch for the More screen. Turning on is always a deliberate tap — iOS only
 * shows the permission prompt for one, and browsers distrust sites that ask unprompted. */
export function PushCard() {
  const t = useTranslations("pwa.push");
  const status = usePushStatus();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  if (status === "unsupported") return null;

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setFailed(false);
    try {
      await action();
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  if (status === "needs-install" || status === "blocked") {
    return (
      <div className="flex items-center gap-3 rounded-2xl border border-border bg-surface-card p-4 shadow-sm">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-surface-subtle text-ink-muted">
          <BellOff className="size-5" aria-hidden />
        </span>
        <p className="text-xs text-ink-muted">{status === "blocked" ? t("blocked") : t("needsInstall")}</p>
      </div>
    );
  }

  const on = status === "on";
  return (
    <div className="space-y-2 rounded-2xl border border-border bg-surface-card p-4 shadow-sm">
      <div className="flex items-center gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-accent-soft text-accent">
          <Bell className="size-5" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-bold text-ink">{on ? t("onTitle") : t("title")}</h3>
          <p className="text-xs text-ink-muted">{on ? t("onDescription") : t("description")}</p>
        </div>
        <button
          type="button"
          disabled={busy}
          onClick={() => void run(on ? disablePush : enablePush)}
          className="shrink-0 cursor-pointer rounded-xl bg-accent px-3 py-2 text-xs font-semibold text-ink-inverse transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-60"
        >
          {on ? t("disable") : t("enable")}
        </button>
      </div>
      {failed && (
        <p role="alert" className="text-xs text-status-critical">
          {t("failed")}
        </p>
      )}
    </div>
  );
}
