import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import admissions from "@/messages/en/admissions.json";
import { AdmissionWizard } from "../AdmissionWizard";

const LOCALE = "en";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

const api = vi.hoisted(() => ({
  listProperties: vi.fn(),
  getPropertyLayout: vi.fn(),
  listBuildings: vi.fn(),
  listFloors: vi.fn(),
  listRooms: vi.fn(),
  createResident: vi.fn(),
  updateResidentStatus: vi.fn(),
  createAdmission: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...api,
}));

const bed = (id: string, number: string, status = "available") => ({ id, bed_number: number, status });
const room = (id: string, number: string, beds: ReturnType<typeof bed>[]) => ({
  id,
  room_number: number,
  sharing_type: 2,
  rack_rate_with_food: "12000.00",
  rack_rate_without_food: "10000.00",
  beds,
});

const LAYOUT = {
  redacted: [],
  buildings: [
    { id: "b1", name: "Block A", floors: [{ id: "f1", name: "Ground", rooms: [{ id: "r1", room_number: "G01", beds: [{ id: "bed-other", bed_number: "G01-A", availability: "available" }] }] }] },
    { id: "b2", name: "Block B", floors: [
      { id: "f2a", name: "Ground", rooms: [] },
      { id: "f2b", name: "1st", rooms: [{ id: "r2", room_number: "101", beds: [
        { id: "bed-taken", bed_number: "101-A", availability: "occupied" },
        { id: "bed-target", bed_number: "101-B", availability: "available" },
      ] }] },
    ] },
  ],
};

/** Resolves a loader later than the others, to prove a slow response cannot overwrite the requested bed. */
function delayed<T>(value: T, ms: number) {
  return new Promise<T>((resolve) => setTimeout(() => resolve(value), ms));
}

function setUpApi() {
  api.listProperties.mockResolvedValue([{ id: "p0", name: "Other PG" }, { id: "p1", name: "Greenwood" }]);
  api.getPropertyLayout.mockResolvedValue(LAYOUT);
  // The first building / first floor are NOT the requested ones, and arrive slowly.
  api.listBuildings.mockImplementation(() => delayed([{ id: "b1", name: "Block A" }, { id: "b2", name: "Block B" }], 20));
  api.listFloors.mockImplementation((buildingId: string) =>
    delayed(buildingId === "b2" ? [{ id: "f2a", name: "Ground" }, { id: "f2b", name: "1st" }] : [{ id: "f1", name: "Ground" }], 20)
  );
  api.listRooms.mockImplementation((floorId: string) =>
    delayed(
      floorId === "f2b"
        ? [room("r2", "101", [bed("bed-taken", "101-A", "occupied"), bed("bed-target", "101-B")])]
        : floorId === "f1"
          ? [room("r1", "G01", [bed("bed-other", "G01-A")])]
          : [],
      20
    )
  );
}

function renderWizard(preselect?: { propertyId: string; bedId?: string }) {
  return render(
    <NextIntlClientProvider locale={LOCALE} messages={{ admissions }}>
      <AdmissionWizard preselect={preselect} />
    </NextIntlClientProvider>
  );
}

function completeStep1() {
  fireEvent.change(screen.getByPlaceholderText(admissions.step1.placeholderName), { target: { value: "Rahul Sharma" } });
  fireEvent.change(screen.getByPlaceholderText(admissions.step1.placeholderEmail), { target: { value: "r@example.com" } });
  fireEvent.change(screen.getByPlaceholderText(admissions.step1.placeholderPhone), { target: { value: "9876543210" } });
  fireEvent.click(screen.getByRole("button", { name: new RegExp(admissions.controls.next) }));
}

const SELECTED = (room: string, bedNumber: string) =>
  admissions.step2.selectedSlotDetail.replace("{room}", room).replace("{bed}", bedNumber);

describe("AdmissionWizard preselection from the Vacancies screen", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setUpApi();
  });

  test("stays on step 1 and still requires the resident's details", async () => {
    renderWizard({ propertyId: "p1", bedId: "bed-target" });

    expect(screen.getByText(admissions.step1.heading)).toBeInTheDocument();
    await waitFor(() => expect(api.getPropertyLayout).toHaveBeenCalledWith("p1"));

    // Next with nothing filled in is refused by step 1's own validation.
    fireEvent.click(screen.getByRole("button", { name: new RegExp(admissions.controls.next) }));
    expect(screen.getByText(admissions.step1.heading)).toBeInTheDocument();
    expect(screen.queryByText(admissions.step2.heading)).toBeNull();
  });

  test("step 2 opens with the whole chain and the requested bed selected, even though the loaders default to the first of each", async () => {
    renderWizard({ propertyId: "p1", bedId: "bed-target" });
    completeStep1();

    expect(await screen.findByText(admissions.step2.heading)).toBeInTheDocument();
    expect(await screen.findByText(SELECTED("101", "101-B"), undefined, { timeout: 2000 })).toBeInTheDocument();
    // Not the other building's bed that the "first of each" defaults would have led to.
    expect(screen.queryByText(SELECTED("G01", "G01-A"))).toBeNull();
  });

  test("an unknown bed id falls back to the normal wizard: nothing preselected", async () => {
    renderWizard({ propertyId: "p1", bedId: "does-not-exist" });
    completeStep1();

    expect(await screen.findByText(admissions.step2.heading)).toBeInTheDocument();
    await waitFor(() => expect(api.listRooms).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(screen.queryByText(/Selected Slot/)).toBeNull();
  });

  test("a bed that is no longer free is not preselected", async () => {
    renderWizard({ propertyId: "p1", bedId: "bed-taken" });
    completeStep1();

    expect(await screen.findByText(admissions.step2.heading)).toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(screen.queryByText(/Selected Slot/)).toBeNull();
  });

  test("a property alone (Getting started checklist) selects that property, not the first one", async () => {
    renderWizard({ propertyId: "p1" });

    await waitFor(() => expect(api.listBuildings).toHaveBeenCalledWith("p1"));
    expect(api.listBuildings).not.toHaveBeenCalledWith("p0");
    expect(api.getPropertyLayout).not.toHaveBeenCalled(); // no bed to resolve
  });

  test("a stale bed keeps the requested property and selects no bed", async () => {
    renderWizard({ propertyId: "p1", bedId: "does-not-exist" });

    await waitFor(() => expect(api.listBuildings).toHaveBeenCalledWith("p1"));
    expect(api.listBuildings).not.toHaveBeenCalledWith("p0");
  });

  test("a property the user can't see falls back to the first property", async () => {
    renderWizard({ propertyId: "p-gone" });

    await waitFor(() => expect(api.listBuildings).toHaveBeenCalledWith("p0"));
  });

  test("without a preselection nothing changes: the first property, building and floor load as before", async () => {
    renderWizard();

    await waitFor(() => expect(api.listBuildings).toHaveBeenCalledWith("p0"));
    expect(api.getPropertyLayout).not.toHaveBeenCalled();
  });
});

describe("AdmissionWizard completing the admission", () => {
  const next = () => fireEvent.click(screen.getByRole("button", { name: new RegExp(admissions.controls.next) }));

  beforeEach(() => {
    vi.clearAllMocks();
    setUpApi();
    api.createResident.mockResolvedValue({ id: "res-1" });
    api.updateResidentStatus.mockResolvedValue({ id: "res-1", status: "reserved" });
    api.createAdmission.mockResolvedValue({ id: "adm-1" });
  });

  // The status API only allows Inquiry -> Reserved -> Active, and creating the admission performs
  // Reserved -> Active itself, so the wizard must reserve and never set "active" (it used to, and
  // the API refused with "Cannot move a resident from Inquiry to active").
  test("reserves the resident and lets the admission check them in, with the fields the API requires", async () => {
    renderWizard({ propertyId: "p1", bedId: "bed-target" });
    completeStep1();
    await screen.findByText(SELECTED("101", "101-B"), undefined, { timeout: 2000 });
    next(); // step 2 -> 3
    await screen.findByText(admissions.step3.heading);
    next(); // step 3 -> 4
    await screen.findByText(admissions.step4.heading);
    fireEvent.click(screen.getByRole("button", { name: new RegExp(admissions.controls.complete) }));

    await waitFor(() => expect(api.createAdmission).toHaveBeenCalledTimes(1));
    expect(api.createResident).toHaveBeenCalledWith(expect.objectContaining({ property: "p1", first_name: "Rahul", last_name: "Sharma" }));
    expect(api.updateResidentStatus).toHaveBeenCalledTimes(1);
    expect(api.updateResidentStatus).toHaveBeenCalledWith("res-1", "reserved");
    expect(api.updateResidentStatus).not.toHaveBeenCalledWith(expect.anything(), "active");
    // The status call happens before the admission that needs a Reserved resident.
    expect(api.updateResidentStatus.mock.invocationCallOrder[0]).toBeLessThan(api.createAdmission.mock.invocationCallOrder[0]);
    // A collected amount needs its date and a mode the API knows.
    expect(api.createAdmission).toHaveBeenCalledWith(
      expect.objectContaining({
        resident: "res-1",
        bed: "bed-target",
        advance_collected_date: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
        advance_mode: "upi",
      })
    );
  });

  test("bank transfer is sent as the API's bank_transfer mode", async () => {
    renderWizard({ propertyId: "p1", bedId: "bed-target" });
    completeStep1();
    await screen.findByText(SELECTED("101", "101-B"), undefined, { timeout: 2000 });
    next();
    await screen.findByText(admissions.step3.heading);
    next();
    await screen.findByText(admissions.step4.heading);
    fireEvent.click(screen.getByRole("button", { name: new RegExp(admissions.step4.modeBank) }));
    fireEvent.click(screen.getByRole("button", { name: new RegExp(admissions.controls.complete) }));

    await waitFor(() => expect(api.createAdmission).toHaveBeenCalledWith(expect.objectContaining({ advance_mode: "bank_transfer" })));
  });
});

describe("AdmissionWizard collecting only part of the money at admission", () => {
  const next = () => fireEvent.click(screen.getByRole("button", { name: new RegExp(admissions.controls.next) }));
  const complete = () => fireEvent.click(screen.getByRole("button", { name: new RegExp(admissions.controls.complete) }));
  const paidNow = (key: "rent" | "deposit") => document.getElementById(`paid-now-${key}`) as HTMLInputElement;
  const setPaid = (key: "rent" | "deposit", value: string) => fireEvent.change(paidNow(key), { target: { value } });

  async function toStep4() {
    renderWizard({ propertyId: "p1", bedId: "bed-target" });
    completeStep1();
    await screen.findByText(SELECTED("101", "101-B"), undefined, { timeout: 2000 });
    next();
    await screen.findByText(admissions.step3.heading);
    next();
    await screen.findByText(admissions.step4.heading);
  }

  beforeEach(() => {
    vi.clearAllMocks();
    setUpApi();
    api.createResident.mockResolvedValue({ id: "res-1" });
    api.updateResidentStatus.mockResolvedValue({ id: "res-1", status: "reserved" });
    api.createAdmission.mockResolvedValue({ id: "adm-1" });
  });

  test("both amounts start at the full agreed amount, with nothing pending", async () => {
    await toStep4();

    // 12000.00 is the with-food rate of the room and 5000.00 the default deposit.
    expect(paidNow("rent").value).toBe("12000.00");
    expect(paidNow("deposit").value).toBe("5000.00");
    expect(screen.getByText("₹17,000.00")).toBeInTheDocument(); // total received now
    expect(screen.getAllByText("₹0.00").length).toBeGreaterThanOrEqual(3); // pending rent, deposit and total
  });

  test("a part payment sends what was paid, the agreed deposit, and a date and mode for each paid amount", async () => {
    await toStep4();
    setPaid("rent", "3000");
    setPaid("deposit", "2000");

    expect(screen.getByText("₹9,000.00")).toBeInTheDocument(); // pending rent
    expect(screen.getByText("₹3,000.00", { selector: "p" })).toBeInTheDocument(); // pending deposit
    complete();

    await waitFor(() => expect(api.createAdmission).toHaveBeenCalledTimes(1));
    expect(api.createAdmission).toHaveBeenCalledWith(
      expect.objectContaining({
        advance_amount: "3000.00",
        advance_mode: "upi",
        advance_collected_date: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
        security_deposit_agreed: "5000.00",
        security_deposit_amount: "2000.00",
        security_deposit_mode: "upi",
        security_deposit_collected_date: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
      })
    );
  });

  test("nothing paid now sends zero amounts with no date or mode, and hides the mode picker", async () => {
    await toStep4();
    setPaid("rent", "0");
    setPaid("deposit", "");

    expect(screen.queryByText(admissions.step4.paymentMethod)).toBeNull();
    complete();

    await waitFor(() => expect(api.createAdmission).toHaveBeenCalledTimes(1));
    const payload = api.createAdmission.mock.calls[0][0];
    expect(payload).toMatchObject({ advance_amount: "0.00", security_deposit_agreed: "5000.00", security_deposit_amount: "0.00" });
    for (const key of ["advance_mode", "advance_collected_date", "security_deposit_mode", "security_deposit_collected_date"]) {
      expect(payload).not.toHaveProperty(key);
    }
  });

  test("only the deposit paid sends a collected date and mode for the deposit alone", async () => {
    await toStep4();
    setPaid("rent", "0");
    complete();

    await waitFor(() => expect(api.createAdmission).toHaveBeenCalledTimes(1));
    const payload = api.createAdmission.mock.calls[0][0];
    expect(payload).toMatchObject({ advance_amount: "0.00", security_deposit_amount: "5000.00", security_deposit_mode: "upi" });
    expect(payload).not.toHaveProperty("advance_mode");
    expect(payload).not.toHaveProperty("advance_collected_date");
  });

  test("paying more than agreed is refused before anything is created", async () => {
    await toStep4();
    setPaid("rent", "12000.01");
    setPaid("deposit", "5001");
    complete();

    expect(await screen.findByText(admissions.step4.errRentExceeds)).toBeInTheDocument();
    expect(screen.getByText(admissions.step4.errDepositExceeds)).toBeInTheDocument();
    expect(api.createResident).not.toHaveBeenCalled();
    expect(api.createAdmission).not.toHaveBeenCalled();
  });

  test("an amount that is not a number is refused", async () => {
    await toStep4();
    setPaid("deposit", "abc");
    complete();

    expect(await screen.findByText(admissions.step4.errInvalidAmount)).toBeInTheDocument();
    expect(api.createAdmission).not.toHaveBeenCalled();
  });

  test("the payment modes are the ones the API accepts: UPI, cash and bank transfer, not card", async () => {
    await toStep4();

    expect(screen.getByRole("button", { name: admissions.step4.modeUpi })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: admissions.step4.modeCash })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: admissions.step4.modeBank })).toBeInTheDocument();
    expect(screen.queryByText(/Card/i)).toBeNull();
  });

  test("the agreed rent is read-only: the contracted rent is the room's rate", async () => {
    renderWizard({ propertyId: "p1", bedId: "bed-target" });
    completeStep1();
    await screen.findByText(SELECTED("101", "101-B"), undefined, { timeout: 2000 });
    next();
    await screen.findByText(admissions.step3.heading);

    const rent = screen.getByDisplayValue("12000.00") as HTMLInputElement;
    expect(rent.readOnly).toBe(true);
  });
});

describe("AdmissionWizard dates are the local calendar day", () => {
  const originalTZ = process.env.TZ;

  beforeEach(() => {
    vi.clearAllMocks();
    setUpApi();
    api.createResident.mockResolvedValue({ id: "res-1" });
    api.updateResidentStatus.mockResolvedValue({ id: "res-1", status: "reserved" });
    api.createAdmission.mockResolvedValue({ id: "adm-1" });
    process.env.TZ = "Asia/Kolkata";
    // 02:00 IST on 1 Nov is still 31 Oct in UTC: the case where `toISOString()` gave yesterday.
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-31T20:30:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
    if (originalTZ === undefined) delete process.env.TZ;
    else process.env.TZ = originalTZ;
  });

  test("the joining date and the payment dates are today in India, and today can be picked", async () => {
    renderWizard({ propertyId: "p1", bedId: "bed-target" });
    completeStep1();
    await screen.findByText(SELECTED("101", "101-B"), undefined, { timeout: 2000 });
    fireEvent.click(screen.getByRole("button", { name: new RegExp(admissions.controls.next) }));
    await screen.findByText(admissions.step3.heading);
    fireEvent.click(screen.getByRole("button", { name: new RegExp(admissions.controls.next) }));
    await screen.findByText(admissions.step4.heading);

    const date = document.getElementById("collected-on") as HTMLInputElement;
    expect(date.value).toBe("2026-11-01");
    expect(date.max).toBe("2026-11-01");

    fireEvent.click(screen.getByRole("button", { name: new RegExp(admissions.controls.complete) }));
    await waitFor(() => expect(api.createAdmission).toHaveBeenCalledTimes(1));
    expect(api.createAdmission).toHaveBeenCalledWith(
      expect.objectContaining({
        joining_date: "2026-11-01",
        advance_collected_date: "2026-11-01",
        security_deposit_collected_date: "2026-11-01",
      })
    );
  });
});
