"use client";

import { useTranslations } from "next-intl";
import { LOCALES } from "@/i18n/config";

function languageName(code: string) {
  return LOCALES.find((locale) => locale.code === code)?.nativeName ?? code;
}

/** "Shown in English — తెలుగు version coming soon" when the server stood in another language. */
export function FallbackLanguageNote({ shown, requested }: { shown: string; requested: string }) {
  const t = useTranslations("onboarding.video");
  if (shown === requested) return null;
  return (
    <p className="text-xs text-ink-muted">
      {t("fallbackNote", { shown: languageName(shown), requested: languageName(requested) })}
    </p>
  );
}
