/**
 * Comparison key for PG feature names, mirroring the backend's
 * `apps.properties.feature_catalog.normalise` exactly: NFKC, lowercase, then
 * keep only Unicode letters, combining marks and numbers. Marks stay because
 * Indic vowel signs are marks — dropping them makes distinct Telugu/Hindi
 * words collide. Both sides are asserted against
 * backend/apps/properties/tests/fixtures/feature_normalisation.json.
 *
 * A client-side match is only a fast path; the server stays authoritative.
 */
export function normaliseFeatureText(text: string): string {
  return text
    .normalize("NFKC")
    .toLowerCase()
    .replace(/[^\p{L}\p{M}\p{N}]+/gu, "");
}
