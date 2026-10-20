import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import type { LayoutBed, PropertyLayout } from "@/lib/api";
import { renderWithIntl } from "@/test-utils/renderWithIntl";
import { VacanciesScreen } from "../VacanciesScreen";

const state = vi.hoisted(() => ({
  permissions: new Set<string>(),
  propertyId: null as string | null,
  properties: [] as Array<{ id: string; name: string; city: string; state: string }>,
  getPropertyLayout: vi.fn(),
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), back: vi.fn() }) }));
vi.mock("@/lib/session", () => ({
  useSession: () => ({ ready: true, authenticated: true, can: (code: string) => state.permissions.has(code) }),
}));
vi.mock("@/components/shared/PropertyFilter", () => ({
  useActiveProperty: () => ({
    propertyId: state.propertyId,
    properties: state.properties,
    listLoaded: true,
    accessRevoked: false,
    setPropertyId: vi.fn(),
  }),
}));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  getPropertyLayout: state.getPropertyLayout,
}));

const COUNTS = { total: 0, occupied: 0, reserved: 0, maintenance: 0, available: 0, occupancy_rate: null };

const bed = (id: string, number: string, availability: LayoutBed["availability"], resident: LayoutBed["resident"] = null): LayoutBed =>
  ({ id, bed_number: number, availability, resident }) as LayoutBed;

function layout(name: string, buildings: Array<{ name: string; floor: string; rooms: Array<{ id: string; number: string; beds: LayoutBed[] }> }>, redacted: string[] = []): PropertyLayout {
  return {
    property: { id: "x", name },
    period: "2026-10",
    as_of: "2026-10-20",
    due_soon_days: 3,
    counts: COUNTS,
    finance: null,
    redacted,
    buildings: buildings.map((b, index) => ({
      id: `b${index}`,
      name: b.name,
      order: index,
      counts: COUNTS,
      floors: [
        {
          id: `f${index}`,
          name: b.floor,
          order: 0,
          counts: COUNTS,
          rooms: b.rooms.map((r) => ({
            id: r.id,
            room_number: r.number,
            sharing_type: 2,
            category: "non_ac",
            status: "available",
            rack_rate_with_food: "12000.00",
            rack_rate_without_food: "10000.00",
            counts: COUNTS,
            beds: r.beds,
          })),
        },
      ],
    })),
  };
}

const NOTICE = {
  id: "res-1",
  name: "Amit Kumar",
  phone: "9876543212",
  status: "notice_period",
  on_notice: true,
  notice_date: "2026-07-28",
  expected_vacate_date: "2026-08-27",
  is_temporary: false,
};

const GREENWOOD = layout("Greenwood", [{ name: "Main", floor: "Ground Floor", rooms: [{ id: "g01", number: "G01", beds: [bed("g01b", "G01-B", "available")] }] }]);
const SUNSHINE = layout("Sunshine", [
  {
    name: "Main",
    floor: "1st Floor",
    rooms: [{ id: "s101", number: "101", beds: [bed("s101a", "101-A", "available"), bed("s101b", "101-B", "occupied", NOTICE)] }],
  },
]);

beforeEach(() => {
  state.permissions = new Set(["view_property_features", "view_resident_profile", "manage_admissions"]);
  state.propertyId = null;
  state.properties = [
    { id: "p1", name: "Greenwood Girls Hostel", city: "Hyderabad", state: "Telangana" },
    { id: "p2", name: "Sunshine Boys PG", city: "Bengaluru", state: "Karnataka" },
  ];
  state.getPropertyLayout.mockReset();
  state.getPropertyLayout.mockImplementation(async (id: string) => (id === "p1" ? GREENWOOD : SUNSHINE));
});

describe("VacanciesScreen", () => {
  test("summarises vacant beds and residents on notice, and lists each property's qualifying rooms", async () => {
    renderWithIntl(<VacanciesScreen />);

    // Wait for the layouts (the property pill's hidden select also lists the names, so a name alone proves nothing).
    expect(await screen.findByText("Room G01")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Greenwood Girls Hostel" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Sunshine Boys PG" })).toBeInTheDocument();
    expect(screen.getByText("Hyderabad, Telangana")).toBeInTheDocument();

    expect(screen.getByText("Vacant Beds").previousElementSibling).toHaveTextContent("2");
    expect(screen.getByText("On Notice").previousElementSibling).toHaveTextContent("1");
    expect(screen.getAllByText("1 vacant")).toHaveLength(2); // one pill per property
    expect(screen.getByText("1 on notice")).toBeInTheDocument();

    expect(screen.getByText("Room G01")).toBeInTheDocument();
    expect(screen.getByText("Bed G01-B")).toBeInTheDocument();
    expect(screen.getAllByText("from ₹10,000/mo")).toHaveLength(2); // the lower of 12,000 and 10,000, in each room
    expect(screen.getByText("Amit Kumar", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("Notice: 28-07-2026")).toBeInTheDocument();
    expect(screen.getByText(/Vacating: 27-08-2026/)).toBeInTheDocument();
  });

  test("+ Admit links to the wizard with the property and bed, and only with manage_admissions", async () => {
    const { unmount } = renderWithIntl(<VacanciesScreen />);
    const admit = await screen.findByRole("link", { name: "Admit a resident to bed G01-B" });
    expect(admit).toHaveAttribute("href", "/admissions?property=p1&bed=g01b");
    unmount();

    state.permissions.delete("manage_admissions");
    renderWithIntl(<VacanciesScreen />);
    await screen.findByText("Bed G01-B");
    expect(screen.queryByRole("link", { name: /Admit a resident/ })).toBeNull();
  });

  test("without resident access the On Notice tile, pills and section are hidden, not shown as zero", async () => {
    const redacted = layout("Sunshine", [{ name: "Main", floor: "1st", rooms: [{ id: "s101", number: "101", beds: [bed("s101a", "101-A", "available"), bed("s101b", "101-B", "occupied", null)] }] }], ["resident"]);
    state.getPropertyLayout.mockResolvedValue(redacted);
    state.propertyId = "p2";
    renderWithIntl(<VacanciesScreen />);

    await screen.findByText("Room 101");
    expect(screen.getByText("Vacant Beds")).toBeInTheDocument();
    expect(screen.queryByText("On Notice")).toBeNull();
    expect(screen.queryByText(/on notice/i)).toBeNull();
    expect(screen.queryByText("On notice (upcoming)")).toBeNull();
  });

  test("one property failing still renders the others, with a retry row for the failed one", async () => {
    state.getPropertyLayout.mockImplementation(async (id: string) => {
      if (id === "p2") throw new Error("boom");
      return GREENWOOD;
    });
    renderWithIntl(<VacanciesScreen />);

    expect(await screen.findByText("Room G01")).toBeInTheDocument();
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("Couldn't load Sunshine Boys PG.")).toBeInTheDocument();
    expect(screen.getByText("Some properties failed to load, so these totals are partial.")).toBeInTheDocument();

    // Retry refetches just that property.
    state.getPropertyLayout.mockImplementation(async () => SUNSHINE);
    state.getPropertyLayout.mockClear();
    fireEvent.click(within(alert).getByRole("button", { name: /retry/i }));
    await waitFor(() => expect(state.getPropertyLayout).toHaveBeenCalledWith("p2"));
    expect(state.getPropertyLayout).not.toHaveBeenCalledWith("p1");
  });

  test("every property failing shows one full error with retry, not a blank page", async () => {
    state.getPropertyLayout.mockRejectedValue(new Error("down"));
    renderWithIntl(<VacanciesScreen />);

    expect(await screen.findByText("Couldn't load vacancies.")).toBeInTheDocument();
    expect(screen.queryByText("Vacant Beds")).toBeNull();
  });

  test("nothing vacant and nobody on notice shows the empty message", async () => {
    state.getPropertyLayout.mockResolvedValue(layout("Full", [{ name: "Main", floor: "1st", rooms: [{ id: "r", number: "101", beds: [bed("b", "101-A", "occupied")] }] }]));
    renderWithIntl(<VacanciesScreen />);
    expect(await screen.findByText("No vacant beds or residents on notice.")).toBeInTheDocument();
  });

  test("the picked property limits which layouts are fetched", async () => {
    state.propertyId = "p1";
    renderWithIntl(<VacanciesScreen />);
    await screen.findByText("Room G01");
    expect(state.getPropertyLayout).toHaveBeenCalledWith("p1");
    expect(state.getPropertyLayout).not.toHaveBeenCalledWith("p2");
  });

  test("two buildings in one property with the same room number show two cards labelled by building", async () => {
    state.propertyId = "p1";
    state.getPropertyLayout.mockResolvedValue(
      layout("Greenwood", [
        { name: "Block A", floor: "Ground Floor", rooms: [{ id: "ra", number: "101", beds: [bed("a1", "101-A", "available")] }] },
        { name: "Block B", floor: "Ground Floor", rooms: [{ id: "rb", number: "101", beds: [bed("b1", "101-A", "available")] }] },
      ])
    );
    renderWithIntl(<VacanciesScreen />);

    await screen.findAllByText("Room 101");
    expect(screen.getAllByText("Room 101")).toHaveLength(2);
    expect(screen.getByText("· Block A · Ground Floor")).toBeInTheDocument();
    expect(screen.getByText("· Block B · Ground Floor")).toBeInTheDocument();
  });
});
