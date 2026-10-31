import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { ApiError } from "@/lib/api";
import {
  copy,
  deferred,
  holiday,
  OWNER,
  PROPERTIES,
  PROPERTY_A,
  PROPERTY_B,
  renderWithMessages,
} from "./testUtils";

const api = vi.hoisted(() => ({
  createFoodHoliday: vi.fn(),
  updateFoodHoliday: vi.fn(),
  getPropertySettings: vi.fn(),
  listProperties: vi.fn(),
}));
const session = vi.hoisted(() => ({ permissions: new Set<string>() }));
const refresh = vi.hoisted(() => ({ afterFoodHolidayChange: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, ...api };
});
vi.mock("@/lib/session", () => ({
  useSession: () => ({ ready: true, authenticated: true, can: (code: string) => session.permissions.has(code) }),
}));
vi.mock("@/lib/refresh", () => refresh);

import { FoodHolidayFormSheet } from "../FoodHolidayFormSheet";

const form = copy.holidayForm;
const onClose = vi.fn();

const settings = (rate: string | null) => ({ id: "s", food_charge_per_day: rate });

function rateInput() {
  return screen.getByLabelText(form.rate) as HTMLInputElement;
}

function fillDates(start = "2026-10-20", end = "2026-10-23") {
  fireEvent.change(screen.getByLabelText(form.startDate), { target: { value: start } });
  fireEvent.change(screen.getByLabelText(form.endDate), { target: { value: end } });
}

async function submit(label: string) {
  fireEvent.click(screen.getByRole("button", { name: label }));
  await act(async () => {});
}

beforeEach(() => {
  for (const fn of [...Object.values(api), refresh.afterFoodHolidayChange, onClose]) fn.mockReset();
  session.permissions = new Set(OWNER);
  api.listProperties.mockResolvedValue(PROPERTIES);
  api.getPropertySettings.mockResolvedValue(settings("100.00"));
  api.createFoodHoliday.mockResolvedValue(holiday());
  api.updateFoodHoliday.mockResolvedValue(holiday());
});

describe("FoodHolidayFormSheet → rate default (new holiday)", () => {
  test("is pre-filled from the property's food charge", async () => {
    renderWithMessages(<FoodHolidayFormSheet defaultProperty={PROPERTY_A} onClose={onClose} />);
    fireEvent.click(screen.getByLabelText(new RegExp(form.adjust)));

    await waitFor(() => expect(rateInput().value).toBe("100.00"));
    expect(api.getPropertySettings).toHaveBeenCalledWith(PROPERTY_A);
  });

  test("a slow settings response never overwrites a rate the user already typed", async () => {
    const slow = deferred<ReturnType<typeof settings>>();
    api.getPropertySettings.mockReturnValue(slow.promise);
    renderWithMessages(<FoodHolidayFormSheet defaultProperty={PROPERTY_A} onClose={onClose} />);
    fireEvent.click(screen.getByLabelText(new RegExp(form.adjust)));

    fireEvent.change(rateInput(), { target: { value: "75" } });
    await act(async () => slow.resolve(settings("100.00")));

    expect(rateInput().value).toBe("75");
  });

  test("a late response for the previous property can't win after switching property", async () => {
    const slowA = deferred<ReturnType<typeof settings>>();
    api.getPropertySettings.mockImplementation((id: string) =>
      id === PROPERTY_A ? slowA.promise : Promise.resolve(settings("120.00"))
    );
    renderWithMessages(<FoodHolidayFormSheet defaultProperty={PROPERTY_A} onClose={onClose} />);
    fireEvent.click(screen.getByLabelText(new RegExp(form.adjust)));
    await screen.findByRole("option", { name: "Lakeview PG" });
    fireEvent.change(screen.getByLabelText(form.property), { target: { value: PROPERTY_B } });
    await waitFor(() => expect(rateInput().value).toBe("120.00"));

    await act(async () => slowA.resolve(settings("100.00")));
    expect(rateInput().value).toBe("120.00");
  });

  test("says so when the property has no default rate", async () => {
    api.getPropertySettings.mockResolvedValue(settings(null));
    renderWithMessages(<FoodHolidayFormSheet defaultProperty={PROPERTY_A} onClose={onClose} />);
    fireEvent.click(screen.getByLabelText(new RegExp(form.adjust)));

    expect(await screen.findByText(form.rateNoDefault)).toBeTruthy();
    expect(rateInput().value).toBe("");
  });

  test("creates with the rate, dates and notice choice", async () => {
    renderWithMessages(<FoodHolidayFormSheet defaultProperty={PROPERTY_A} onClose={onClose} />);
    fireEvent.change(screen.getByLabelText(form.name), { target: { value: "Dasara" } });
    fillDates();
    fireEvent.click(screen.getByLabelText(new RegExp(form.adjust)));
    await waitFor(() => expect(rateInput().value).toBe("100.00"));
    await submit(form.submit);

    expect(api.createFoodHoliday).toHaveBeenCalledWith({
      property: PROPERTY_A,
      name: "Dasara",
      start_date: "2026-10-20",
      end_date: "2026-10-23",
      adjust_in_bill: true,
      rate_per_day: "100.00",
      post_notice: true,
    });
    expect(refresh.afterFoodHolidayChange).toHaveBeenCalled();
  });
});

describe("FoodHolidayFormSheet → editing", () => {
  test("keeps the holiday's own rate: never reads the property default, and a rename sends only the name", async () => {
    // Holiday rate 80, property default 100. Opening Edit must not let the default replace it.
    renderWithMessages(<FoodHolidayFormSheet initial={holiday({ rate_per_day: "80.00" })} defaultProperty={null} onClose={onClose} />);

    expect(rateInput().value).toBe("80.00");
    fireEvent.change(screen.getByLabelText(form.name), { target: { value: "Vijayadashami" } });
    await submit(form.save);

    expect(api.getPropertySettings).not.toHaveBeenCalled();
    expect(api.updateFoodHoliday).toHaveBeenCalledWith(expect.any(String), { name: "Vijayadashami" });
  });

  test("a redacted rate is neither shown nor sent back", async () => {
    session.permissions = new Set(["view_notices", "manage_notices"]);
    const redacted = holiday({ adjust_in_bill: false });
    delete redacted.rate_per_day;
    renderWithMessages(<FoodHolidayFormSheet initial={redacted} defaultProperty={null} onClose={onClose} />);

    expect(screen.queryByLabelText(new RegExp(form.adjust))).toBeNull();
    expect(screen.queryByLabelText(form.rate)).toBeNull();
    fireEvent.change(screen.getByLabelText(form.name), { target: { value: "Renamed" } });
    await submit(form.save);

    expect(api.updateFoodHoliday).toHaveBeenCalledWith(expect.any(String), { name: "Renamed" });
  });

  test("a holiday on an issued bill locks its dates, adjustment and rate, but not its name", async () => {
    renderWithMessages(<FoodHolidayFormSheet initial={holiday({ is_locked: true })} defaultProperty={null} onClose={onClose} />);

    expect(screen.getByText(form.lockedNote)).toBeTruthy();
    expect((screen.getByLabelText(form.startDate) as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByLabelText(form.endDate) as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByLabelText(new RegExp(form.adjust)) as HTMLInputElement).disabled).toBe(true);
    expect(rateInput().disabled).toBe(true);
    expect((screen.getByLabelText(form.name) as HTMLInputElement).disabled).toBe(false);
  });

  test("changing only the dates sends only the dates", async () => {
    renderWithMessages(<FoodHolidayFormSheet initial={holiday()} defaultProperty={null} onClose={onClose} />);

    fireEvent.change(screen.getByLabelText(form.endDate), { target: { value: "2026-10-24" } });
    await submit(form.save);

    expect(api.updateFoodHoliday).toHaveBeenCalledWith(expect.any(String), { end_date: "2026-10-24" });
  });
});

describe("FoodHolidayFormSheet → a refresh while the sheet is open", () => {
  test("a rename doesn't send back the rate or dates another manager changed meanwhile", async () => {
    const opened = holiday({ rate_per_day: "80.00", end_date: "2026-10-23" });
    const view = renderWithMessages(<FoodHolidayFormSheet initial={opened} defaultProperty={null} onClose={onClose} />);

    // Someone else raises the rate and extends the holiday; the query refetches and the prop changes.
    view.rerenderWith(
      <FoodHolidayFormSheet
        initial={holiday({ rate_per_day: "100.00", end_date: "2026-10-24" })}
        defaultProperty={null}
        onClose={onClose}
      />
    );
    fireEvent.change(screen.getByLabelText(form.name), { target: { value: "Vijayadashami" } });
    await submit(form.save);

    expect(api.updateFoodHoliday).toHaveBeenCalledWith(expect.any(String), { name: "Vijayadashami" });
  });

  test("what the user did edit is still sent", async () => {
    const view = renderWithMessages(
      <FoodHolidayFormSheet initial={holiday({ rate_per_day: "80.00" })} defaultProperty={null} onClose={onClose} />
    );
    view.rerenderWith(
      <FoodHolidayFormSheet initial={holiday({ rate_per_day: "100.00" })} defaultProperty={null} onClose={onClose} />
    );
    fireEvent.change(rateInput(), { target: { value: "90" } });
    await submit(form.save);

    expect(api.updateFoodHoliday).toHaveBeenCalledWith(expect.any(String), { rate_per_day: "90" });
  });

  test("a holiday that becomes locked while open stops accepting date and rate changes", async () => {
    const view = renderWithMessages(
      <FoodHolidayFormSheet initial={holiday()} defaultProperty={null} onClose={onClose} />
    );
    view.rerenderWith(
      <FoodHolidayFormSheet initial={holiday({ is_locked: true })} defaultProperty={null} onClose={onClose} />
    );

    expect(screen.getByText(form.lockedNote)).toBeTruthy();
    expect((screen.getByLabelText(form.endDate) as HTMLInputElement).disabled).toBe(true);
    expect(rateInput().disabled).toBe(true);
  });
});

describe("FoodHolidayFormSheet → rules and errors", () => {
  test("the bill-adjustment switch and rate are hidden without manage_invoices", async () => {
    session.permissions = new Set(["view_notices", "manage_notices", "view_finance"]);
    renderWithMessages(<FoodHolidayFormSheet defaultProperty={PROPERTY_A} onClose={onClose} />);
    fireEvent.change(screen.getByLabelText(form.name), { target: { value: "Diwali" } });
    fillDates();

    expect(screen.queryByLabelText(new RegExp(form.adjust))).toBeNull();
    await submit(form.submit);

    const payload = api.createFoodHoliday.mock.calls[0][0];
    expect(payload).not.toHaveProperty("adjust_in_bill");
    expect(payload).not.toHaveProperty("rate_per_day");
  });

  test("a last day before the first day is blocked on the client", async () => {
    renderWithMessages(<FoodHolidayFormSheet defaultProperty={PROPERTY_A} onClose={onClose} />);
    fireEvent.change(screen.getByLabelText(form.name), { target: { value: "Dasara" } });
    fillDates("2026-10-23", "2026-10-20");
    await submit(form.submit);

    expect(screen.getByText(form.endBeforeStart)).toBeTruthy();
    expect(api.createFoodHoliday).not.toHaveBeenCalled();
  });

  test("a holiday longer than 366 days is blocked", async () => {
    renderWithMessages(<FoodHolidayFormSheet defaultProperty={PROPERTY_A} onClose={onClose} />);
    fireEvent.change(screen.getByLabelText(form.name), { target: { value: "Long" } });
    fillDates("2026-01-01", "2027-06-01");
    await submit(form.submit);

    expect(screen.getByText("A holiday can be at most 366 days long.")).toBeTruthy();
    expect(api.createFoodHoliday).not.toHaveBeenCalled();
  });

  test("a rate is required, and must be a plain amount, when bills are adjusted", async () => {
    api.getPropertySettings.mockResolvedValue(settings(null));
    renderWithMessages(<FoodHolidayFormSheet defaultProperty={PROPERTY_A} onClose={onClose} />);
    fireEvent.change(screen.getByLabelText(form.name), { target: { value: "Dasara" } });
    fillDates();
    fireEvent.click(screen.getByLabelText(new RegExp(form.adjust)));
    await submit(form.submit);
    expect(screen.getByText(form.rateRequired)).toBeTruthy();

    fireEvent.change(rateInput(), { target: { value: "12.345" } });
    await submit(form.submit);
    expect(screen.getByText(form.rateInvalid)).toBeTruthy();
    expect(api.createFoodHoliday).not.toHaveBeenCalled();
  });

  test("an overlap the server rejects is shown, and the holiday is refetched", async () => {
    api.createFoodHoliday.mockRejectedValue(
      new ApiError(409, { detail: 'These dates overlap "Diwali" (20 Oct 2026 – 22 Oct 2026).', code: "holiday_overlap" })
    );
    renderWithMessages(<FoodHolidayFormSheet defaultProperty={PROPERTY_A} onClose={onClose} />);
    fireEvent.change(screen.getByLabelText(form.name), { target: { value: "Dasara" } });
    fillDates();
    await submit(form.submit);

    expect(screen.getByRole("alert").textContent).toContain("overlap");
    expect(refresh.afterFoodHolidayChange).toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  test("a holiday locked by someone else meanwhile shows the server's reason", async () => {
    api.updateFoodHoliday.mockRejectedValue(
      new ApiError(409, { detail: "This holiday is already on an issued bill or a settlement.", code: "holiday_locked" })
    );
    renderWithMessages(<FoodHolidayFormSheet initial={holiday()} defaultProperty={null} onClose={onClose} />);
    fireEvent.change(screen.getByLabelText(form.endDate), { target: { value: "2026-10-25" } });
    await submit(form.save);

    expect(screen.getByRole("alert").textContent).toContain("already on an issued bill");
    expect(refresh.afterFoodHolidayChange).toHaveBeenCalled();
  });
});
