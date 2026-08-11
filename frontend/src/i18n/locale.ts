import { DEFAULT_LOCALE, LOCALES } from "./config";

export const COOKIE_NAME = "NEXT_LOCALE";

export function isValidLocale(locale: string): boolean {
  return LOCALES.some((l) => l.code === locale);
}

export function readLocaleCookie(): string {
  if (typeof document === "undefined") return DEFAULT_LOCALE;
  const match = document.cookie.match(new RegExp(`(?:^|; )${COOKIE_NAME}=([^;]*)`));
  const value = match ? decodeURIComponent(match[1]) : undefined;
  return value && isValidLocale(value) ? value : DEFAULT_LOCALE;
}

export function writeLocaleCookie(locale: string): void {
  if (typeof document === "undefined") return;
  const validLocale = isValidLocale(locale) ? locale : DEFAULT_LOCALE;
  // Cookie valid for 1 year across all paths
  document.cookie = `${COOKIE_NAME}=${encodeURIComponent(validLocale)}; path=/; max-age=31536000; SameSite=Lax`;
}
