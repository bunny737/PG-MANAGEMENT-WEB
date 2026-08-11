import assert from "node:assert";
import fs from "node:fs";
import path from "node:path";
import { LOCALES, isActiveLocale } from "../config";
import commonEn from "../../messages/en/common.json";
import commonHi from "../../messages/hi/common.json";

export function testI18nConfig() {
  const expectedCodes = ["en", "hi", "te", "ta", "ml"];
  const actualCodes = LOCALES.map((l) => l.code);
  assert.deepStrictEqual(actualCodes, expectedCodes);

  // MVP scope (owner decision 2026-08-11): English + Telugu active, the rest
  // remain selectable-but-disabled until translated.
  assert.deepStrictEqual(
    LOCALES.filter((l) => isActiveLocale(l.code)).map((l) => l.code),
    ["en", "te"]
  );

  const checkKeys = (targetObj: Record<string, unknown>, sourceObj: Record<string, unknown>) => {
    for (const key in targetObj) {
      assert.ok(key in sourceObj, `Key ${key} missing in English catalog`);
      const targetVal = targetObj[key];
      const sourceVal = sourceObj[key];
      if (typeof targetVal === "object" && targetVal !== null && typeof sourceVal === "object" && sourceVal !== null) {
        checkKeys(targetVal as Record<string, unknown>, sourceVal as Record<string, unknown>);
      }
    }
  };
  checkKeys(commonHi as Record<string, unknown>, commonEn as Record<string, unknown>);

  // Telugu is an active MVP language — it must have FULL key parity with
  // English for every catalog it ships, not just a subset (unlike hi/v2).
  const checkFullParity = (activeObj: Record<string, unknown>, enObj: Record<string, unknown>, pathPrefix = "") => {
    for (const key in enObj) {
      const keyPath = pathPrefix ? `${pathPrefix}.${key}` : key;
      assert.ok(key in activeObj, `Key ${keyPath} missing in Telugu catalog`);
      const enVal = enObj[key];
      const activeVal = activeObj[key];
      if (typeof enVal === "object" && enVal !== null) {
        checkFullParity(activeVal as Record<string, unknown>, enVal as Record<string, unknown>, keyPath);
      }
    }
  };

  const messagesDir = path.resolve(__dirname, "../../messages");
  const enDir = path.join(messagesDir, "en");
  const teDir = path.join(messagesDir, "te");

  if (fs.existsSync(enDir)) {
    const files = fs.readdirSync(enDir).filter((f) => f.endsWith(".json"));
    for (const file of files) {
      const enFilePath = path.join(enDir, file);
      const teFilePath = path.join(teDir, file);

      assert.ok(fs.existsSync(teFilePath), `Telugu catalog missing for ${file}`);

      const enObj = JSON.parse(fs.readFileSync(enFilePath, "utf8"));
      const teObj = JSON.parse(fs.readFileSync(teFilePath, "utf8"));

      checkFullParity(teObj, enObj, file);
    }
  }
}
