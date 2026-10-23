import { describe, expect, test } from "vitest";
import { normalizePhoneE164, toDialDigits } from "../phone";

describe("normalizePhoneE164", () => {
  test("accepts a plain 10-digit Indian mobile number", () => {
    expect(normalizePhoneE164("9876543210")).toBe("+919876543210");
  });

  test("accepts common formatting around the digits", () => {
    expect(normalizePhoneE164("+91 98765 43210")).toBe("+919876543210");
    expect(normalizePhoneE164("0-9876543210")).toBe("+919876543210");
    expect(normalizePhoneE164("91 9876543210")).toBe("+919876543210");
  });

  test("rejects a landline-shaped or too-short/long number", () => {
    expect(normalizePhoneE164("1234567890")).toBeNull(); // doesn't start 6-9
    expect(normalizePhoneE164("98765")).toBeNull();
    expect(normalizePhoneE164("987654321099")).toBeNull();
  });

  test("rejects non-numeric input", () => {
    expect(normalizePhoneE164("not a phone")).toBeNull();
    expect(normalizePhoneE164("")).toBeNull();
  });
});

describe("toDialDigits", () => {
  test("strips the leading + for tel:/wa.me/sms: links", () => {
    expect(toDialDigits("+919876543210")).toBe("919876543210");
  });
});
