/**
 * Phone normalisation for the contact actions (Call/WhatsApp/SMS) on the
 * resident card and layout bed tiles. The product targets India only
 * today (default region IN, PRD §2), so this is a small hand-rolled
 * normaliser rather than a full libphonenumber dependency — it accepts
 * the same shapes `LoginForm.normalizeInputPhone` already does for the
 * staff phone-login field, so the two can't disagree on what's a valid
 * Indian mobile number.
 */

const INDIAN_MOBILE = /^[6-9]\d{9}$/;

/** Returns the number as E.164 (`+91XXXXXXXXXX`), or null if it isn't a
 * recognisable 10-digit Indian mobile number (optionally with a `0` or
 * `91`/`+91` prefix). Callers disable the action rather than guess. */
export function normalizePhoneE164(raw: string): string | null {
  const digits = raw.replace(/\D/g, "");
  let national: string | null = null;
  if (digits.length === 10) {
    national = digits;
  } else if (digits.length === 11 && digits.startsWith("0")) {
    national = digits.slice(1);
  } else if (digits.length === 12 && digits.startsWith("91")) {
    national = digits.slice(2);
  }
  if (!national || !INDIAN_MOBILE.test(national)) return null;
  return `+91${national}`;
}

/** `tel:` / `https://wa.me/` / `sms:` links take digits without the `+`. */
export function toDialDigits(e164: string): string {
  return e164.replace(/^\+/, "");
}
