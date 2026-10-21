// Copy for the crash screens. app/global-error.tsx replaces the root layout, so it has no
// next-intl provider: the five catalogs are imported statically and the locale is picked here.
import { COOKIE_NAME } from "@/i18n/locale";
import en from "@/messages/en/errors.json";
import hi from "@/messages/hi/errors.json";
import ml from "@/messages/ml/errors.json";
import ta from "@/messages/ta/errors.json";
import te from "@/messages/te/errors.json";

const CATALOGS = { en, te, hi, ta, ml };

export type ErrorLocale = keyof typeof CATALOGS;
export type ErrorCopy = typeof en;

const isErrorLocale = (value: string | undefined): value is ErrorLocale =>
  value !== undefined && Object.prototype.hasOwnProperty.call(CATALOGS, value);

/** The locale cookie wins; otherwise the first browser language we have a catalog for; else English. */
export function pickErrorLocale(cookieHeader: string, languages: readonly string[]): ErrorLocale {
  const match = cookieHeader.match(new RegExp(`(?:^|; )${COOKIE_NAME}=([^;]*)`));
  const fromCookie = match ? decodeURIComponent(match[1]) : undefined;
  if (isErrorLocale(fromCookie)) return fromCookie;
  for (const language of languages) {
    const base = language.toLowerCase().split("-")[0];
    if (isErrorLocale(base)) return base;
  }
  return "en";
}

/** "Reference: <digest>" in the catalog's wording, or undefined when the error has no digest. */
export function errorReference(copy: ErrorCopy, digest?: string): string | undefined {
  return digest ? copy.reference.replace("{code}", digest) : undefined;
}

export function errorCopyFor(locale: string): ErrorCopy {
  return isErrorLocale(locale) ? CATALOGS[locale] : CATALOGS.en;
}
