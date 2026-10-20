import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, test, vi } from "vitest";
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

function renderWizard(preselect?: { propertyId: string; bedId: string }) {
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

  test("without a preselection nothing changes: the first property, building and floor load as before", async () => {
    renderWizard();

    await waitFor(() => expect(api.listBuildings).toHaveBeenCalledWith("p0"));
    expect(api.getPropertyLayout).not.toHaveBeenCalled();
  });
});
