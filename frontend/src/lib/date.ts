const pad = (n: number) => String(n).padStart(2, "0");

/** Formats an API date ("YYYY-MM-DD") or datetime (ISO 8601) as DD-MM-YYYY.
 * Returns `fallback` for empty or unparseable input. Plain dates are split as
 * strings, never routed through `Date`, so a timezone can't shift the day. */
export function formatDate(value: string | Date | null | undefined, fallback = "--"): string {
  if (!value) return fallback;
  if (typeof value === "string") {
    const plain = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
    if (plain) return `${plain[3]}-${plain[2]}-${plain[1]}`;
  }
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return fallback;
  return `${pad(date.getDate())}-${pad(date.getMonth() + 1)}-${date.getFullYear()}`;
}

/** DD-MM-YYYY HH:mm (24-hour, local time) for an ISO datetime. */
export function formatDateTime(value: string | Date | null | undefined, fallback = "--"): string {
  if (!value) return fallback;
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return fallback;
  return `${formatDate(date)} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** The local calendar day of `date` as "YYYY-MM-DD" (not UTC: a payment at 11:30 PM
 * IST must count as today in India, not as tomorrow's UTC date). */
export function localDateKey(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** Whether a timestamp (a full ISO instant or a date-only string) falls on the device's
 * local calendar day `now`. A date-only string already names a calendar day, so it is compared as is. */
export function isLocalToday(value: string, now: Date = new Date()): boolean {
  const today = localDateKey(now);
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value === today;
  const parsed = new Date(value);
  return !Number.isNaN(parsed.getTime()) && localDateKey(parsed) === today;
}
