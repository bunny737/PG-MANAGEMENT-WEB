import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import type { Resident } from "@/lib/api";
import { renderWithIntl } from "@/test-utils/renderWithIntl";
import { ResidentsPhoneList, rentLine } from "../ResidentsPhoneList";

const state = vi.hoisted(() => ({ permissions: new Set<string>() }));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), back: vi.fn() }) }));
vi.mock("@/lib/session", () => ({
  useSession: () => ({ ready: true, authenticated: true, can: (code: string) => state.permissions.has(code) }),
}));
vi.mock("@/components/shared/PropertyFilter", () => ({
  useActiveProperty: () => ({ propertyId: null, properties: [], listLoaded: true, accessRevoked: false, setPropertyId: vi.fn() }),
}));

const resident = (overrides: Partial<Resident>): Resident =>
  ({
    id: "r1",
    status: "active",
    first_name: "Rahul",
    last_name: "Sharma",
    phone: "9876543210",
    contracted_rent: "7500.00",
    ...overrides,
  }) as Resident;

function renderList(residents: Resident[], extra: Partial<React.ComponentProps<typeof ResidentsPhoneList>> = {}) {
  const props = {
    residents,
    isLoading: false,
    isError: false,
    onRetry: vi.fn(),
    searchTerm: "",
    onSearchChange: vi.fn(),
    status: "all" as const,
    onStatusChange: vi.fn(),
    ...extra,
  };
  renderWithIntl(<ResidentsPhoneList {...props} />);
  return props;
}

beforeEach(() => {
  state.permissions = new Set(["view_resident_profile", "view_finance", "manage_admissions"]);
});

describe("rentLine (permission first: absence without view_finance means hidden, not unset)", () => {
  const format = (amount: string) => `fmt(${amount})`;

  test("without view_finance there is no rent line, whatever the value", () => {
    expect(rentLine(false, "7500.00", format, "Rent not set")).toBeNull();
    expect(rentLine(false, undefined, format, "Rent not set")).toBeNull();
    expect(rentLine(false, null, format, "Rent not set")).toBeNull();
  });

  test("with view_finance and a value it is the formatted amount", () => {
    expect(rentLine(true, "7500.00", format, "Rent not set")).toBe("fmt(7500.00)");
  });

  test("with view_finance and no value it says rent is not set", () => {
    expect(rentLine(true, null, format, "Rent not set")).toBe("Rent not set");
    expect(rentLine(true, undefined, format, "Rent not set")).toBe("Rent not set");
  });
});

describe("ResidentsPhoneList", () => {
  test("shows name, phone, monthly rent and a status badge per resident", () => {
    renderList([resident({}), resident({ id: "r2", first_name: "Amit", last_name: "Kumar", status: "notice_period", phone: "9876543212", contracted_rent: "8500.00" })]);

    expect(screen.getByText("Rahul Sharma")).toBeInTheDocument();
    expect(screen.getByText("9876543210")).toBeInTheDocument();
    expect(screen.getByText("₹7,500/mo")).toBeInTheDocument();
    expect(screen.getByText("₹8,500/mo")).toBeInTheDocument();
    expect(screen.getByText("Notice Period")).toHaveAttribute("data-status", "notice_period");
  });

  test("without view_finance the rent line is omitted entirely and not replaced by 'Rent not set'", () => {
    state.permissions.delete("view_finance");
    renderList([resident({ contracted_rent: undefined })]);

    expect(screen.queryByText(/\/mo/)).toBeNull();
    expect(screen.queryByText("Rent not set")).toBeNull();
  });

  test("with view_finance and a null rent (an inquiry) it says Rent not set", () => {
    renderList([resident({ status: "inquiry", contracted_rent: null })]);
    expect(screen.getByText("Rent not set")).toBeInTheDocument();
    expect(screen.getByText("Inquiry")).toHaveAttribute("data-status", "inquiry");
  });

  test("the avatar is the first letter of the first name", () => {
    renderList([resident({ first_name: "priya", last_name: "Patel" })]);
    expect(screen.getByText("P")).toBeInTheDocument();
  });

  test("cards link to the resident's profile", () => {
    renderList([resident({ id: "abc" })]);
    expect(screen.getByRole("link", { name: /Rahul Sharma/ })).toHaveAttribute("href", "/residents/abc");
  });

  test("the Admit Resident button is there with manage_admissions", () => {
    renderList([resident({})]);
    expect(screen.getByRole("link", { name: "Admit Resident" })).toHaveAttribute("href", "/admissions");
  });

  test("no Admit Resident button without manage_admissions", () => {
    state.permissions.delete("manage_admissions");
    renderList([resident({})]);
    expect(screen.queryByRole("link", { name: "Admit Resident" })).toBeNull();
  });

  test("status chips are a radio group; choosing one reports it, and the current one is checked", () => {
    const props = renderList([resident({})], { status: "active" });
    const group = screen.getByRole("radiogroup", { name: "Filter by status" });
    expect(group).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Active" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "All" })).toHaveAttribute("aria-checked", "false");

    fireEvent.click(screen.getByRole("radio", { name: "Vacated" }));
    expect(props.onStatusChange).toHaveBeenCalledWith("vacated");
  });

  test("typing in search reports the text", () => {
    const props = renderList([resident({})]);
    fireEvent.change(screen.getByRole("searchbox", { name: "Search residents" }), { target: { value: "amit" } });
    expect(props.onSearchChange).toHaveBeenCalledWith("amit");
  });

  test("empty and error states", () => {
    renderList([]);
    expect(screen.getByText("No Residents Found")).toBeInTheDocument();
  });

  test("an error shows a retry", () => {
    const props = renderList([], { isError: true });
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(props.onRetry).toHaveBeenCalled();
  });
});
