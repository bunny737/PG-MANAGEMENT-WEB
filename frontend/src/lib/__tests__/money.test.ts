import { describe, expect, test } from "vitest";
import { addMoney, compareMoney, formatMoney, formatMoneyCompact, isAtMost, isMoneyInput, subtractMoney, toMoneyString } from "../money";

describe("subtractMoney / addMoney / toMoneyString", () => {
  test("work in integer paise, so there is no float drift", () => {
    expect(subtractMoney("12000.00", "3000")).toBe("9000.00");
    expect(subtractMoney("0.3", "0.1")).toBe("0.20");
    expect(addMoney("0.1", "0.2")).toBe("0.30");
    expect(addMoney("12000.00", "5000.00")).toBe("17000.00");
  });

  test("a negative result keeps its sign", () => {
    expect(subtractMoney("100.00", "250.50")).toBe("-150.50");
  });

  test("anything that is not a plain Decimal string gives null", () => {
    expect(subtractMoney("abc", "1")).toBeNull();
    expect(addMoney("1", "")).toBeNull();
  });

  test("toMoneyString writes the API's two-place form and leaves junk alone", () => {
    expect(toMoneyString("5000")).toBe("5000.00");
    expect(toMoneyString("5000.5")).toBe("5000.50");
    expect(toMoneyString("12x")).toBe("12x");
  });

  test("isMoneyInput accepts non-negative amounts of at most two places", () => {
    for (const ok of ["0", "0.00", "5000", "12.5"]) expect(isMoneyInput(ok), ok).toBe(true);
    for (const bad of ["", "-1", "1.234", "1e3", "abc", " "]) expect(isMoneyInput(bad), bad).toBe(false);
  });
});

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

describe("formatMoneyCompact", () => {
  test("drops .00 from whole amounts only", () => {
    expect(formatMoneyCompact("12000.00")).toBe("₹12,000");
    expect(formatMoneyCompact("7500")).toBe("₹7,500");
    expect(formatMoneyCompact("7500.50")).toBe("₹7,500.50");
    expect(formatMoneyCompact("1234567.00")).toBe("₹12,34,567");
  });

  test("dash for null/undefined and raw string for unparseable, like formatMoney", () => {
    expect(formatMoneyCompact(null)).toBe("—");
    expect(formatMoneyCompact(undefined)).toBe("—");
    expect(formatMoneyCompact("n/a")).toBe("n/a");
  });
});
