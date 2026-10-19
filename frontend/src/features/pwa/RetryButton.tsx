"use client";

import { useTranslations } from "next-intl";

export function RetryButton() {
  const t = useTranslations("pwa.offline");
  return (
    <button
      type="button"
      // While the service worker is serving this page the URL is still the one that was
      // requested, so a reload retries that page for real once the connection is back.
      onClick={() => window.location.reload()}
      className="cursor-pointer rounded-xl bg-accent px-5 py-2.5 text-sm font-semibold text-ink-inverse transition-colors hover:bg-accent-hover"
    >
      {t("retry")}
    </button>
  );
}
