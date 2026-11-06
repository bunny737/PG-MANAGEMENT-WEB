import { beforeEach, describe, expect, test, vi } from "vitest";

const client = vi.hoisted(() => ({ invalidateQueries: vi.fn() }));

vi.mock("@/lib/queryClient", () => ({ queryClient: client }));
vi.mock("@/lib/session", () => ({ ensureFreshSession: vi.fn() }));

import {
  afterFoodHolidayChange,
  afterInvoiceChange,
  afterInvoiceIssued,
  afterNoticeChange,
  afterPayment,
  afterVacate,
} from "../refresh";

function invalidatedRoots(): string[] {
  return client.invalidateQueries.mock.calls.map(([arg]) => String(arg.queryKey[0]));
}

beforeEach(() => {
  client.invalidateQueries.mockReset();
  client.invalidateQueries.mockResolvedValue(undefined);
});

// Module 24: food-holiday credits ride on invoices, so anything that creates, edits, issues or deletes an
// invoice (or settles a stay) can change a holiday's credits and its lock. Those screens must refresh too.
describe("refresh contract → notices (food-holiday credits)", () => {
  test.each([
    ["afterInvoiceChange", () => afterInvoiceChange()],
    ["afterInvoiceIssued", () => afterInvoiceIssued()],
    ["afterVacate", () => afterVacate()],
    ["afterFoodHolidayChange", () => afterFoodHolidayChange()],
    ["afterNoticeChange", () => afterNoticeChange()],
  ])("%s refreshes the notices family", async (_name, run) => {
    await run();
    expect(invalidatedRoots()).toContain("notices");
  });

  test("a payment doesn't touch credits, so it leaves notices alone", async () => {
    await afterPayment();
    expect(invalidatedRoots()).not.toContain("notices");
  });

  test("an invoice change still refreshes what it always did", async () => {
    await afterInvoiceChange({ invoiceId: "i1" });
    expect(invalidatedRoots()).toEqual(expect.arrayContaining(["invoices", "analytics", "dashboard", "notices"]));
  });
});
