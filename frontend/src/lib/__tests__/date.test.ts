import { describe, expect, test } from "vitest";
import { formatDateDMY, isLocalToday, localDateKey } from "../date";

describe("formatDateDMY", () => {
  test("formats a date-only string from its own digits (no timezone shift)", () => {
    expect(formatDateDMY("2026-08-27")).toBe("27-08-2026");
    expect(formatDateDMY("2026-01-01")).toBe("01-01-2026");
  });

  test("accepts an ISO timestamp and returns the date part as written", () => {
    expect(formatDateDMY("2026-08-27T23:30:00+05:30")).toBe("27-08-2026");
  });

  test("dash for empty, raw string for unrecognised input", () => {
    expect(formatDateDMY(null)).toBe("—");
    expect(formatDateDMY("")).toBe("—");
    expect(formatDateDMY("soon")).toBe("soon");
  });
});

describe("local today checks", () => {
  const now = new Date(2026, 9, 20, 23, 30); // 20 Oct 2026, 11:30 PM local

  test("localDateKey uses the local calendar day", () => {
    expect(localDateKey(now)).toBe("2026-10-20");
  });

  test("a timestamp from earlier the same local day counts as today", () => {
    expect(isLocalToday(new Date(2026, 9, 20, 0, 5).toISOString(), now)).toBe(true);
  });

  test("yesterday and tomorrow do not", () => {
    expect(isLocalToday(new Date(2026, 9, 19, 23, 59).toISOString(), now)).toBe(false);
    expect(isLocalToday(new Date(2026, 9, 21, 0, 1).toISOString(), now)).toBe(false);
  });

  test("a date-only string is compared as the calendar day it names", () => {
    expect(isLocalToday("2026-10-20", now)).toBe(true);
    expect(isLocalToday("2026-10-21", now)).toBe(false);
  });

  test("garbage is not today", () => {
    expect(isLocalToday("nope", now)).toBe(false);
  });
});
