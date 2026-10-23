import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import type { Property } from "@/lib/api";
import { renderWithIntl } from "@/test-utils/renderWithIntl";
import { filterByActiveProperty, PropertiesPhoneList } from "../PropertiesPhoneList";

const state = vi.hoisted(() => ({ permissions: new Set<string>(), propertyId: null as string | null }));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), back: vi.fn() }) }));
vi.mock("@/lib/session", () => ({
  useSession: () => ({ ready: true, authenticated: true, can: (code: string) => state.permissions.has(code) }),
}));
vi.mock("@/components/shared/PropertyFilter", () => ({
  useActiveProperty: () => ({
    propertyId: state.propertyId,
    properties: [],
    listLoaded: true,
    accessRevoked: false,
    setPropertyId: vi.fn(),
  }),
}));

const property = (id: string, name: string, city: string, type = "pg"): Property =>
  ({ id, name, city, state: "Telangana", property_type: type }) as unknown as Property;

const PROPERTIES = [
  property("p1", "Greenwood Girls Hostel", "Hyderabad", "girls_hostel"),
  property("p2", "Keshav PG for men", "Hyderabad"),
  property("p3", "Sunshine Boys PG", "Bengaluru", "boys_hostel"),
];

beforeEach(() => {
  state.permissions = new Set(["manage_properties"]);
  state.propertyId = null;
});

describe("filterByActiveProperty", () => {
  test("All Properties (null) returns everything; a selection returns only that property", () => {
    expect(filterByActiveProperty(PROPERTIES, null)).toHaveLength(3);
    expect(filterByActiveProperty(PROPERTIES, "p2").map((p) => p.id)).toEqual(["p2"]);
  });

  test("a selection that matches nothing gives an empty list, not everything", () => {
    expect(filterByActiveProperty(PROPERTIES, "gone")).toEqual([]);
  });
});

describe("PropertiesPhoneList", () => {
  test("All Properties shows every property with its location and type", () => {
    renderWithIntl(<PropertiesPhoneList properties={PROPERTIES} error="" onRetry={vi.fn()} />);

    expect(screen.getByText("Greenwood Girls Hostel")).toBeInTheDocument();
    expect(screen.getByText("Keshav PG for men")).toBeInTheDocument();
    expect(screen.getByText("Sunshine Boys PG")).toBeInTheDocument();
    expect(screen.getAllByText(/Hyderabad, Telangana/)).toHaveLength(2);
    expect(screen.getByRole("link", { name: /Sunshine Boys PG/ })).toHaveAttribute("href", "/properties/p3");
  });

  test("selecting a property in the pill filters the list to that property", () => {
    state.propertyId = "p2";
    renderWithIntl(<PropertiesPhoneList properties={PROPERTIES} error="" onRetry={vi.fn()} />);

    expect(screen.getByText("Keshav PG for men")).toBeInTheDocument();
    expect(screen.queryByText("Greenwood Girls Hostel")).toBeNull();
    expect(screen.queryByText("Sunshine Boys PG")).toBeNull();
  });

  test("a selection with no match says so, instead of looking like the account has no properties", () => {
    state.propertyId = "gone";
    renderWithIntl(<PropertiesPhoneList properties={PROPERTIES} error="" onRetry={vi.fn()} />);
    expect(screen.getByText("No properties match this selection.")).toBeInTheDocument();
    expect(screen.queryByText("No properties registered yet")).toBeNull();
  });

  test("an account with no properties at all gets the empty state", () => {
    renderWithIntl(<PropertiesPhoneList properties={[]} error="" onRetry={vi.fn()} />);
    expect(screen.getByText("No properties registered yet")).toBeInTheDocument();
  });

  test("Add Property is offered with manage_properties and not without it", () => {
    const { unmount } = renderWithIntl(<PropertiesPhoneList properties={PROPERTIES} error="" onRetry={vi.fn()} />);
    expect(screen.getByRole("link", { name: "Add Property" })).toHaveAttribute("href", "/properties/add");
    unmount();

    state.permissions.delete("manage_properties");
    renderWithIntl(<PropertiesPhoneList properties={PROPERTIES} error="" onRetry={vi.fn()} />);
    expect(screen.queryByRole("link", { name: "Add Property" })).toBeNull();
  });
});
