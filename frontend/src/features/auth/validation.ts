// Client-side checks shared by the login and signup forms. The backend re-validates everything;
// these only catch obvious mistakes before a round trip.

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function isValidEmail(value: string): boolean {
  return EMAIL_RE.test(value);
}

/** Mirrors the backend's `normalize_phone`: 10 digits starting 6–9, optionally prefixed with 0 or
 * 91. Returns the canonical 10 digits, or null for any other shape. */
export function normalizeInputPhone(value: string): string | null {
  const digits = value.replace(/\D/g, "");
  if (digits.length === 10 && /^[6-9]/.test(digits)) return digits;
  if (digits.length === 11 && digits.startsWith("0") && /^[6-9]/.test(digits.slice(1))) return digits.slice(1);
  if (digits.length === 12 && digits.startsWith("91") && /^[6-9]/.test(digits.slice(2))) return digits.slice(2);
  return null;
}
