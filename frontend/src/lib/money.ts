/**
 * Money helpers (invariant F1 — money is a string, never arithmetic on the
 * client). The API always sends a Decimal string such as `"7000.00"`.
 * `formatMoney` is display-only; `compareMoney` is for a UX-only check
 * (e.g. "amount <= balance" before submitting a payment) and never decides
 * what the server will accept — the server re-checks under a lock either way.
 */

const DISPLAY_FORMATTER = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** Parses a Decimal string into integer paise, never a float. Returns null
 * for anything that isn't a plain `-?\d+(\.\d{1,2})?` string. */
function toPaise(value: string): number | null {
  const match = /^(-?)(\d+)(?:\.(\d{1,2}))?$/.exec(value.trim());
  if (!match) return null;
  const [, sign, whole, fraction = ""] = match;
  const paise = `${whole}${fraction.padEnd(2, "0")}`;
  const parsed = Number.parseInt(paise, 10);
  if (!Number.isFinite(parsed)) return null;
  return sign === "-" ? -parsed : parsed;
}

/** Formats a Decimal string as "₹7,000.00" for display. Falls back to the
 * raw string (rather than throwing) if the API ever sends something this
 * can't parse — a malformed figure should look wrong, not crash the page. */
export function formatMoney(value: string | null | undefined): string {
  if (value == null) return "—";
  const paise = toPaise(value);
  if (paise === null) return value;
  return DISPLAY_FORMATTER.format(paise / 100);
}

/** Compares two Decimal strings as integer paise. Returns null (not a
 * number) if either side fails to parse, so callers must handle "can't
 * tell" rather than silently treating it as equal. */
export function compareMoney(a: string, b: string): -1 | 0 | 1 | null {
  const pa = toPaise(a);
  const pb = toPaise(b);
  if (pa === null || pb === null) return null;
  if (pa === pb) return 0;
  return pa < pb ? -1 : 1;
}

/** `amount` is not greater than `balance` — the UX-only check the
 * record-payment dialog uses before submitting. */
export function isAtMost(amount: string, balance: string): boolean {
  const cmp = compareMoney(amount, balance);
  return cmp !== null && cmp <= 0;
}

export const ZERO = "0.00";
