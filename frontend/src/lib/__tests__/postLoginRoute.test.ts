import { describe, expect, test } from "vitest";
import { DELETION_PENDING_ROUTE } from "../accountDeletion";
import { postLoginRoute } from "../permissions";

describe("postLoginRoute", () => {
  const deletion = { scope: "user", status: "pending", scheduled_for: "2026-10-31T00:00:00+05:30", can_cancel: true };

  test("a locked account lands on the pending screen, whatever its permissions", () => {
    expect(postLoginRoute({ permissions: ["view_dashboard"], deletion })).toBe(DELETION_PENDING_ROUTE);
    expect(postLoginRoute({ deletion })).toBe(DELETION_PENDING_ROUTE);
  });

  test("an unlocked account goes to its first allowed screen", () => {
    expect(postLoginRoute({ permissions: [], deletion: null })).toBe("/profile");
    expect(postLoginRoute({ permissions: [] })).toBe("/profile");
  });
});
