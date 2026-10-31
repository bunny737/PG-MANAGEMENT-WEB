import { act, fireEvent, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { copy, credit, credits, HOLIDAY_ID, holiday, NOTICE_ID, notice, OWNER, renderWithMessages } from "./testUtils";

const api = vi.hoisted(() => ({
  getFoodHoliday: vi.fn(),
  getNotice: vi.fn(),
  listFoodHolidayCredits: vi.fn(),
  restoreFoodHolidayCredit: vi.fn(),
  deleteFoodHoliday: vi.fn(),
  markNoticeCurrent: vi.fn(),
  deleteNotice: vi.fn(),
  updateNotice: vi.fn(),
  listProperties: vi.fn(),
  getPropertySettings: vi.fn(),
}));
const session = vi.hoisted(() => ({ permissions: new Set<string>() }));
const refresh = vi.hoisted(() => ({ afterFoodHolidayChange: vi.fn(), afterNoticeChange: vi.fn() }));
const nav = vi.hoisted(() => ({ push: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, ...api };
});
vi.mock("@/lib/session", () => ({
  useSession: () => ({ ready: true, authenticated: true, can: (code: string) => session.permissions.has(code) }),
}));
vi.mock("@/lib/refresh", () => refresh);
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: nav.push, replace: vi.fn() }) }));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));

import { FoodHolidayDetail } from "../FoodHolidayDetail";

const detail = copy.detail;
const labels = copy.credits;

// One row per status, plus a clawback on the settled one.
const ROWS = [
  credit({ id: "c-est", resident: "r-est", resident_name: "Estimated Eva", status: "estimated", amount: "400.00", invoice: null }),
  credit({ id: "c-pen", resident: "r-pen", resident_name: "Pending Pat", status: "pending", amount: "200.00", invoice: null }),
  credit({ id: "c-inv", resident: "r-inv", resident_name: "Invoiced Ivan", status: "invoiced", amount: "400.00" }),
  credit({ id: "c-set", resident: "r-set", resident_name: "Settled Sam", status: "settled", amount: "300.00", invoice: null, clawback_amount: "100.00" }),
  credit({ id: "c-wai", resident: "r-wai", resident_name: "Waived Wes", status: "waived", amount: "400.00", invoice: null }),
];
// As the server computes them: credited = pending + invoiced + settled only.
const TOTALS = {
  credited: "900.00",
  credited_count: 3,
  estimated: "400.00",
  estimated_count: 1,
  waived_count: 1,
  clawback: "100.00",
};

function row(name: string) {
  return screen.getByText(name).closest("tr") as HTMLElement;
}

beforeEach(() => {
  for (const fn of [...Object.values(api), ...Object.values(refresh), nav.push]) fn.mockReset();
  session.permissions = new Set(OWNER);
  api.getFoodHoliday.mockResolvedValue(holiday());
  api.getNotice.mockResolvedValue(notice({ food_holiday: HOLIDAY_ID, notice_outdated: true }));
  api.listFoodHolidayCredits.mockResolvedValue(credits(ROWS, TOTALS));
  api.listProperties.mockResolvedValue([]);
});

describe("FoodHolidayDetail → credits", () => {
  test("shows every status as its own chip", async () => {
    renderWithMessages(<FoodHolidayDetail id={HOLIDAY_ID} />);
    await screen.findByText("Pending Pat");

    expect(within(row("Estimated Eva")).getByText(labels.status.estimated)).toBeTruthy();
    expect(within(row("Pending Pat")).getByText(labels.status.pending)).toBeTruthy();
    expect(within(row("Invoiced Ivan")).getByText(labels.status.invoiced)).toBeTruthy();
    expect(within(row("Settled Sam")).getByText(labels.status.settled)).toBeTruthy();
    expect(within(row("Waived Wes")).getByText(labels.status.waived)).toBeTruthy();
    expect(within(row("Invoiced Ivan")).getByRole("link", { name: labels.viewInvoice }).getAttribute("href")).toBe(
      "/billing/invoices/i1"
    );
  });

  test("totals are the server's: credited counts only live credits; estimates, waivers and clawbacks stand apart", async () => {
    renderWithMessages(<FoodHolidayDetail id={HOLIDAY_ID} />);
    await screen.findByText("Pending Pat");

    const tile = (label: string) => screen.getByText(label).closest("div") as HTMLElement;
    // 200 + 400 + 300 = 900. Not 1,700 (all rows) and not 1,300 (live + estimate).
    expect(tile(labels.totals.credited).textContent).toContain("₹900.00");
    expect(tile(labels.totals.estimated).textContent).toContain("₹400.00");
    // A waived credit is a count only, with no amount.
    expect(tile(labels.totals.waived).textContent).not.toContain("₹");
    expect(tile(labels.totals.clawback).textContent).toContain("₹100.00");
  });

  test("the estimated, waived and clawback tiles are left out when there is nothing to show", async () => {
    api.listFoodHolidayCredits.mockResolvedValue(
      credits([credit()], { estimated_count: 0, waived_count: 0, clawback: "0.00" })
    );
    renderWithMessages(<FoodHolidayDetail id={HOLIDAY_ID} />);
    await screen.findByText("Ravi Kumar");

    expect(screen.queryByText(labels.totals.estimated)).toBeNull();
    expect(screen.queryByText(labels.totals.waived)).toBeNull();
    expect(screen.queryByText(labels.totals.clawback)).toBeNull();
  });

  test("turning the adjustment off keeps the retained waived credits visible, without Restore", async () => {
    api.getFoodHoliday.mockResolvedValue(holiday({ adjust_in_bill: false }));
    api.listFoodHolidayCredits.mockResolvedValue(
      credits([ROWS[4]], { credited: "0.00", credited_count: 0, estimated_count: 0, waived_count: 1, clawback: "0.00" })
    );
    renderWithMessages(<FoodHolidayDetail id={HOLIDAY_ID} />);

    expect(await screen.findByText("Waived Wes")).toBeTruthy();
    expect(screen.getByText(detail.notAdjustedNote)).toBeTruthy();
    expect(screen.getByText(labels.totals.waived)).toBeTruthy();
    expect(screen.queryByRole("button", { name: labels.restore })).toBeNull();
  });

  test("with the adjustment off and nothing retained there is no table, only the note", async () => {
    api.getFoodHoliday.mockResolvedValue(holiday({ adjust_in_bill: false }));
    api.listFoodHolidayCredits.mockResolvedValue(credits([], { credited: "0.00", credited_count: 0 }));
    renderWithMessages(<FoodHolidayDetail id={HOLIDAY_ID} />);

    expect(await screen.findByText(detail.notAdjustedNote)).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByText(labels.empty)).toBeNull();
  });

  test("Restore on a waived credit calls the API and refreshes", async () => {
    api.restoreFoodHolidayCredit.mockResolvedValue(credit({ id: "c-wai", status: "pending" }));
    renderWithMessages(<FoodHolidayDetail id={HOLIDAY_ID} />);
    await screen.findByText("Waived Wes");

    expect(within(row("Pending Pat")).queryByRole("button", { name: labels.restore })).toBeNull();
    fireEvent.click(within(row("Waived Wes")).getByRole("button", { name: labels.restore }));
    await act(async () => {});

    expect(api.restoreFoodHolidayCredit).toHaveBeenCalledWith(HOLIDAY_ID, "c-wai");
    expect(refresh.afterFoodHolidayChange).toHaveBeenCalled();
  });

  test("without view_finance the credits are not requested or shown", async () => {
    session.permissions = new Set(["view_notices", "manage_notices"]);
    api.getFoodHoliday.mockResolvedValue(holiday({ adjust_in_bill: false }));
    renderWithMessages(<FoodHolidayDetail id={HOLIDAY_ID} />);
    await screen.findByRole("heading", { name: "Dasara" });

    expect(screen.queryByText(detail.creditsHeading)).toBeNull();
    expect(api.listFoodHolidayCredits).not.toHaveBeenCalled();
  });
});

describe("FoodHolidayDetail → notice and actions", () => {
  test("the linked notice is fetched and carries the out-of-date banner", async () => {
    renderWithMessages(<FoodHolidayDetail id={HOLIDAY_ID} />);

    expect(await screen.findByText(copy.outdated.title)).toBeTruthy();
    expect(api.getNotice).toHaveBeenCalledWith(NOTICE_ID);
    expect(screen.getByRole("button", { name: copy.outdated.dismiss })).toBeTruthy();
  });

  test("a locked holiday can't be deleted, and says why", async () => {
    api.getFoodHoliday.mockResolvedValue(holiday({ is_locked: true }));
    renderWithMessages(<FoodHolidayDetail id={HOLIDAY_ID} />);
    await screen.findByRole("heading", { name: "Dasara" });

    expect((screen.getByRole("button", { name: detail.delete }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(detail.deleteLocked)).toBeTruthy();
  });

  test("Edit and Delete are hidden on a holiday that adjusts bills without manage_invoices", async () => {
    session.permissions = new Set(["view_notices", "manage_notices", "view_finance"]);
    renderWithMessages(<FoodHolidayDetail id={HOLIDAY_ID} />);
    await screen.findByRole("heading", { name: "Dasara" });

    expect(screen.queryByRole("button", { name: detail.edit })).toBeNull();
    expect(screen.queryByRole("button", { name: detail.delete })).toBeNull();
  });

  test("a holiday that doesn't adjust bills can be edited without manage_invoices", async () => {
    session.permissions = new Set(["view_notices", "manage_notices"]);
    api.getFoodHoliday.mockResolvedValue(holiday({ adjust_in_bill: false }));
    renderWithMessages(<FoodHolidayDetail id={HOLIDAY_ID} />);
    await screen.findByRole("heading", { name: "Dasara" });

    expect(screen.getByRole("button", { name: detail.edit })).toBeTruthy();
    expect(screen.getByRole("button", { name: detail.delete })).toBeTruthy();
  });

  test("deleting asks first, then returns to the list", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    api.deleteFoodHoliday.mockResolvedValue(undefined);
    renderWithMessages(<FoodHolidayDetail id={HOLIDAY_ID} />);
    await screen.findByRole("heading", { name: "Dasara" });

    fireEvent.click(screen.getByRole("button", { name: detail.delete }));
    await act(async () => {});

    expect(api.deleteFoodHoliday).toHaveBeenCalledWith(HOLIDAY_ID);
    expect(nav.push).toHaveBeenCalledWith("/notices?tab=holidays");
  });
});
