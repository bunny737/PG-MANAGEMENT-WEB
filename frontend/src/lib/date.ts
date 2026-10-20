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
