/**
 * YYYY-MM helpers for the month navigator and filter URLs. Display-only —
 * every actual period computation (billing periods, due dates, "this
 * month") happens server-side (apps/core/periods.py); this just formats
 * and steps the key the UI already has.
 */

const MONTH_KEY = /^\d{4}-(0[1-9]|1[0-2])$/;

export function isMonthKey(value: string): boolean {
  return MONTH_KEY.test(value);
}

export function currentMonthKey(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

export function addMonths(monthKey: string, delta: number): string {
  const [year, month] = monthKey.split("-").map(Number);
  const date = new Date(year, month - 1 + delta, 1);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

/** "2026-10" -> "October 2026", localized via Intl. */
export function formatMonthLabel(monthKey: string, locale: string): string {
  const [year, month] = monthKey.split("-").map(Number);
  const date = new Date(year, month - 1, 1);
  return new Intl.DateTimeFormat(locale, { month: "long", year: "numeric" }).format(date);
}
