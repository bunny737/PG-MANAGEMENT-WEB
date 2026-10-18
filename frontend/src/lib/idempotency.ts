/**
 * One `Idempotency-Key` per user intent (UX roadmap D3/D5), not per HTTP
 * attempt — a dialog creates one key when it opens and reuses it on every
 * retry of that same submit, so a flaky network retry can't double-record
 * a payment or expense. `useIdempotencyKey()` is the hook form of this for
 * a component that lives for the dialog's open lifetime.
 */
export function createIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  // Fallback for an environment without crypto.randomUUID (old Safari);
  // not cryptographically strong, but this key only needs to be unique
  // per dialog session, never secret.
  return `idem-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}
