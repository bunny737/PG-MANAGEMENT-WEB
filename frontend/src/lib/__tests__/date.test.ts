import { describe, expect, it } from "vitest";
import { formatDate, formatDateTime, isLocalToday, localDateKey } from "../date";

describe("formatDate", () => {
  it("formats a plain API date as DD-MM-YYYY without timezone shifting", () => {
    expect(formatDate("2026-06-08")).toBe("08-06-2026");
  });

  it("formats an ISO datetime as DD-MM-YYYY", () => {
    expect(formatDate("2026-06-08T10:15:00")).toBe("08-06-2026");
  });

  it("returns the fallback for empty or invalid input", () => {
    expect(formatDate(null)).toBe("--");
    expect(formatDate(undefined, "")).toBe("");
    expect(formatDate("not a date")).toBe("--");
  });
});

describe("formatDateTime", () => {
  it("appends a 24-hour HH:mm", () => {
    expect(formatDateTime("2026-06-08T09:05:00")).toBe("08-06-2026 09:05");
  });
});

describe("local today checks", () => {
  const now = new Date(2026, 9, 20, 23, 30); // 20 Oct 2026, 11:30 PM local

  it("localDateKey uses the local calendar day", () => {
    expect(localDateKey(now)).toBe("2026-10-20");
  });

  it("a timestamp from earlier the same local day counts as today", () => {
    expect(isLocalToday(new Date(2026, 9, 20, 0, 5).toISOString(), now)).toBe(true);
  });

  it("yesterday and tomorrow do not", () => {
    expect(isLocalToday(new Date(2026, 9, 19, 23, 59).toISOString(), now)).toBe(false);
    expect(isLocalToday(new Date(2026, 9, 21, 0, 1).toISOString(), now)).toBe(false);
  });

  it("a date-only string is compared as the calendar day it names", () => {
    expect(isLocalToday("2026-10-20", now)).toBe(true);
    expect(isLocalToday("2026-10-21", now)).toBe(false);
  });

  it("garbage is not today", () => {
    expect(isLocalToday("nope", now)).toBe(false);
  });
});
