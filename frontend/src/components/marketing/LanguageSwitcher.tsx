"use client";

import { useRouter } from "next/navigation";
import { useLocale } from "next-intl";
import { Languages } from "lucide-react";
import { LOCALES } from "@/i18n/config";
import { writeLocaleCookie } from "@/i18n/locale";

/** Only locales that ship translations are offered; v2/v3 ones stay hidden here. */
export function LanguageSwitcher({ label }: { label: string }) {
  const router = useRouter();
  const locale = useLocale();
  const options = LOCALES.filter((entry) => entry.status === "active");

  return (
    <label className="relative inline-flex items-center">
      <span className="sr-only">{label}</span>
      <Languages className="pointer-events-none absolute left-2.5 size-4 text-ink-muted" aria-hidden="true" />
      <select
        value={locale}
        onChange={(event) => {
          writeLocaleCookie(event.target.value);
          router.refresh();
        }}
        className="h-10 cursor-pointer appearance-none rounded-xl border border-border-strong bg-surface-card pl-8 pr-3 text-sm font-medium text-ink hover:bg-surface-subtle"
      >
        {options.map((entry) => (
          <option key={entry.code} value={entry.code}>
            {entry.nativeName}
          </option>
        ))}
      </select>
    </label>
  );
}
