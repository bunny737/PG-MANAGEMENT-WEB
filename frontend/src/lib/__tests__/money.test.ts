import { describe, expect, test } from "vitest";
import { compareMoney, formatMoney, isAtMost } from "../money";

describe("formatMoney", () => {
  test("formats a Decimal string as INR", () => {
    expect(formatMoney("7000.00")).toBe("₹7,000.00");
    expect(formatMoney("0.00")).toBe("₹0.00");
    expect(formatMoney("1234567.89")).toBe("₹12,34,567.89"); // en-IN grouping
  });

  test("renders a dash for null/undefined (e.g. a redacted field)", () => {
    expect(formatMoney(null)).toBe("—");
    expect(formatMoney(undefined)).toBe("—");
  });

  test("falls back to the raw string for anything unparseable", () => {
    expect(formatMoney("not-a-number")).toBe("not-a-number");
  });
});

describe("compareMoney", () => {
  test("compares as integer paise, not floats", () => {
    expect(compareMoney("0.1", "0.2")).toBe(-1);
    expect(compareMoney("0.3", "0.1")).toBe(1);
    expect(compareMoney("7000.00", "7000.00")).toBe(0);
    // The classic float trap: 0.1 + 0.2 !== 0.3 in IEEE754, but these are
    // decimal strings, so this must still resolve exactly.
    expect(compareMoney("7000.10", "7000.10")).toBe(0);
  });

  test("returns null (not a number) when either side fails to parse", () => {
    expect(compareMoney("abc", "1.00")).toBeNull();
    expect(compareMoney("1.00", "abc")).toBeNull();
  });
});

describe("isAtMost", () => {
  test("true when amount <= balance, false when it exceeds it", () => {
    expect(isAtMost("5000.00", "7000.00")).toBe(true);
    expect(isAtMost("7000.00", "7000.00")).toBe(true);
    expect(isAtMost("7000.01", "7000.00")).toBe(false);
  });

  test("an unparseable value is never treated as within balance", () => {
    expect(isAtMost("abc", "7000.00")).toBe(false);
  });
});
