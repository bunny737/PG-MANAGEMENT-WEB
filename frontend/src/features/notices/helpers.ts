import { localDateKey } from "@/lib/date";

/** Today's calendar day on this device, "YYYY-MM-DD". */
export function todayKey(): string {
  return localDateKey(new Date());
}

/** A notice is expired once its last day is before today (the day itself still counts). */
export function isExpired(expiresOn: string | null, today: string = todayKey()): boolean {
  return !!expiresOn && expiresOn < today;
}

/** Inclusive number of days from `start` to `end` ("YYYY-MM-DD"); 0 when either is missing or the range is reversed. */
export function dayCount(start: string, end: string): number {
  const first = /^(\d{4})-(\d{2})-(\d{2})$/.exec(start);
  const last = /^(\d{4})-(\d{2})-(\d{2})$/.exec(end);
  if (!first || !last) return 0;
  const from = Date.UTC(Number(first[1]), Number(first[2]) - 1, Number(first[3]));
  const to = Date.UTC(Number(last[1]), Number(last[2]) - 1, Number(last[3]));
  if (to < from) return 0;
  return Math.round((to - from) / 86_400_000) + 1;
}

/** A rate the API accepts: 0 to 999,999.99 with at most two decimals. */
export const RATE_PATTERN = /^\d{1,6}(\.\d{1,2})?$/;

export const MAX_HOLIDAY_DAYS = 366;
