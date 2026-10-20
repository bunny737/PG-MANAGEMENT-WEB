/**
 * Date helpers for display and for "is this today" checks on the phone screens.
 * Display-only: due dates, billing periods and every other business date are computed
 * server-side (apps/core/periods.py).
 */

const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})/;

/** "2026-08-27" (or an ISO timestamp) -> "27-08-2026". A date-only string is
 * formatted from its own digits, never through `new Date()`, so no timezone can shift the day. */
export function formatDateDMY(value: string | null | undefined): string {
  if (!value) return "—";
  const match = DATE_ONLY.exec(value);
  if (!match) return value;
  const [, year, month, day] = match;
  return `${day}-${month}-${year}`;
}

/** The local calendar day of `date` as "YYYY-MM-DD" (not UTC: a payment at 11:30 PM
 * IST must count as today in India, not as tomorrow's UTC date). */
export function localDateKey(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

/** Whether a timestamp (a full ISO instant or a date-only string) falls on the device's
 * local calendar day `now`. A date-only string already names a calendar day, so it is compared as is. */
export function isLocalToday(value: string, now: Date = new Date()): boolean {
  const today = localDateKey(now);
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value === today;
  const parsed = new Date(value);
  return !Number.isNaN(parsed.getTime()) && localDateKey(parsed) === today;
}
