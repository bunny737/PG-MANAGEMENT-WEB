import { describe, expect, it } from "vitest";
import { formatDate, formatDateTime } from "../date";

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
