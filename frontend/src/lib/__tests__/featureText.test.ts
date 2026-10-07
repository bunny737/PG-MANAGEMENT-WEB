import assert from "node:assert";
import fs from "node:fs";
import path from "node:path";
import { normaliseFeatureText } from "../featureText";

// The same cases the backend asserts in test_pg_features (rule 34), so the
// client-side duplicate check can never disagree with the server's.
const FIXTURE = path.resolve(
  __dirname,
  "../../../../backend/apps/properties/tests/fixtures/feature_normalisation.json"
);

export function testFeatureTextMatchesBackend() {
  const cases = JSON.parse(fs.readFileSync(FIXTURE, "utf8")) as { input: string; expected: string }[];
  for (const { input, expected } of cases) {
    assert.strictEqual(normaliseFeatureText(input), expected, `normaliseFeatureText(${JSON.stringify(input)})`);
  }
}
