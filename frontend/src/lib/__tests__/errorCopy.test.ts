import { describe, expect, test } from "vitest";
import en from "@/messages/en/errors.json";
import hi from "@/messages/hi/errors.json";
import ml from "@/messages/ml/errors.json";
import ta from "@/messages/ta/errors.json";
import te from "@/messages/te/errors.json";
import { errorCopyFor, errorReference, pickErrorLocale } from "../errorCopy";

describe("pickErrorLocale", () => {
  test("the locale cookie wins over the browser language", () => {
    expect(pickErrorLocale("a=1; NEXT_LOCALE=te; b=2", ["hi-IN", "en"])).toBe("te");
  });

  test("without a usable cookie, the first browser language we have a catalog for", () => {
    expect(pickErrorLocale("", ["fr-FR", "hi-IN", "te"])).toBe("hi");
    expect(pickErrorLocale("NEXT_LOCALE=xx", ["te-IN"])).toBe("te");
  });

  test("falls back to English", () => {
    expect(pickErrorLocale("", [])).toBe("en");
    expect(pickErrorLocale("NEXT_LOCALE=zz", ["fr", "de"])).toBe("en");
  });

  test("a cookie value can't name an Object.prototype member", () => {
    expect(pickErrorLocale("NEXT_LOCALE=constructor", [])).toBe("en");
    expect(pickErrorLocale("NEXT_LOCALE=toString", [])).toBe("en");
  });
});

describe("errorCopyFor", () => {
  test("returns each locale's catalog and English for anything else", () => {
    expect(errorCopyFor("te")).toBe(te);
    expect(errorCopyFor("hi")).toBe(hi);
    expect(errorCopyFor("nope")).toBe(en);
  });

  test("errorReference fills the digest in, or returns nothing without one", () => {
    expect(errorReference(en, "4821")).toBe("Reference: 4821");
    expect(errorReference(te, "4821")).toContain("4821");
    expect(errorReference(en, undefined)).toBeUndefined();
  });

  test("every catalog carries every key, and the reference keeps its {code} placeholder", () => {
    for (const [name, catalog] of Object.entries({ en, te, hi, ta, ml })) {
      expect(Object.keys(catalog).sort(), name).toEqual(Object.keys(en).sort());
      expect(catalog.reference, name).toContain("{code}");
    }
  });
});
