import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import DashboardPage from "@/app/(owner)/dashboard/page";
import { localDateKey } from "@/lib/date";
import { renderWithIntl } from "@/test-utils/renderWithIntl";
import { QuickActions } from "../QuickActions";
import { WelcomeCard } from "../WelcomeCard";

const state = vi.hoisted(() => ({
  permissions: new Set<string>(),
  propertyId: null as string | null,
  api: {
    getAnalyticsSummary: vi.fn(),
    listComplaints: vi.fn(),
    listAdmissions: vi.fn(),
    listResidents: vi.fn(),
    listPaymentsFiltered: vi.fn(),
  },
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/dashboard",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
}));
vi.mock("@/lib/session", () => ({
  useSession: () => ({
    ready: true,
    authenticated: true,
    role: "owner",
    userName: "Regular User",
    user: { id: "u1", tenant_id: "t1" },
    can: (code: string) => state.permissions.has(code),
  }),
}));
vi.mock("@/components/shared/PropertyFilter", () => ({
  useActiveProperty: () => ({
    propertyId: state.propertyId,
    properties: [{ id: "p1", name: "Greenwood" }],
    listLoaded: true,
    accessRevoked: false,
    setPropertyId: vi.fn(),
  }),
}));
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  ...state.api,
}));

const ALL_PERMISSIONS = [
  "view_dashboard",
  "view_finance",
  "manage_complaints",
  "manage_admissions",
  "view_resident_profile",
  "view_property_features",
  "view_expenses",
];

const SUMMARY = {
  occupancy: { total: 8, occupied: 3, available: 5, occupancy_rate: 37.5 },
  finance: { cash_collected: "0.00", outstanding_total: "0.00", deposits_held: "0.00" },
};

function daysAgo(days: number) {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return localDateKey(date);
}

beforeEach(() => {
  state.permissions = new Set(ALL_PERMISSIONS);
  state.propertyId = null;
  Object.values(state.api).forEach((fn) => fn.mockReset());
  state.api.getAnalyticsSummary.mockResolvedValue(SUMMARY);
  state.api.listComplaints.mockResolvedValue([]);
  state.api.listAdmissions.mockResolvedValue([]);
  state.api.listResidents.mockResolvedValue([]);
  state.api.listPaymentsFiltered.mockResolvedValue([]);
});

describe("QuickActions (phone)", () => {
  const links = () => screen.queryAllByRole("link").map((link) => [link.textContent, link.getAttribute("href")]);

  test("an owner gets Add Resident, Vacancies, Billing and Expenses, in that order", () => {
    renderWithIntl(<QuickActions />);
    expect(links()).toEqual([
      ["Add Resident", "/admissions"],
      ["Vacancies", "/vacancies"],
      ["Billing", "/billing"],
      ["Expenses", "/expenses"],
    ]);
  });

  test("Expenses needs view_expenses (finance access alone does not show it), and Billing is independent of it", () => {
    state.permissions = new Set(["view_finance"]);
    const { unmount } = renderWithIntl(<QuickActions />);
    expect(links().map(([label]) => label)).toEqual(["Billing"]);
    unmount();

    state.permissions = new Set(["view_expenses"]);
    renderWithIntl(<QuickActions />);
    expect(links().map(([label]) => label)).toEqual(["Expenses"]);
  });

  test("each shortcut is gated by the permission of the screen it opens", () => {
    state.permissions = new Set(["view_dashboard"]);
    renderWithIntl(<QuickActions />);
    expect(links()).toEqual([]);
  });

  test("Vacancies appears for any one of the bed-grid entry permissions", () => {
    for (const permission of ["view_property_features", "manage_rooms_beds", "manage_admissions", "manage_allocations"]) {
      state.permissions = new Set([permission]);
      const { unmount } = renderWithIntl(<QuickActions />);
      expect(links().some(([, href]) => href === "/vacancies")).toBe(true);
      unmount();
    }
  });

  test("a front-desk user with no finance access has no Billing shortcut", () => {
    state.permissions = new Set(["manage_admissions", "view_property_features"]);
    renderWithIntl(<QuickActions />);
    expect(links().map(([label]) => label)).toEqual(["Add Resident", "Vacancies"]);
  });
});

describe("WelcomeCard", () => {
  test("greets the signed-in user by name with their role", () => {
    renderWithIntl(<WelcomeCard />);
    expect(screen.getByText("Welcome back,")).toBeInTheDocument();
    expect(screen.getByText("Regular User")).toBeInTheDocument();
    expect(screen.getByText("Owner")).toBeInTheDocument();
  });
});

describe("dashboard sections follow the selected property", () => {
  test("every section's query carries the selected property, not just the summary", async () => {
    state.propertyId = "p1";
    renderWithIntl(<DashboardPage />);

    await waitFor(() => expect(state.api.listPaymentsFiltered).toHaveBeenCalled());
    expect(state.api.getAnalyticsSummary).toHaveBeenCalledWith(expect.objectContaining({ property: "p1" }));
    expect(state.api.listComplaints).toHaveBeenCalledWith({ property: "p1" });
    expect(state.api.listAdmissions).toHaveBeenCalledWith({ property: "p1" });
    expect(state.api.listResidents).toHaveBeenCalledWith("p1");
    expect(state.api.listPaymentsFiltered).toHaveBeenCalledWith(expect.objectContaining({ property: "p1" }));
  });

  test("All Properties sends no property filter", async () => {
    renderWithIntl(<DashboardPage />);

    await waitFor(() => expect(state.api.listPaymentsFiltered).toHaveBeenCalled());
    expect(state.api.listComplaints).toHaveBeenCalledWith({ property: undefined });
    expect(state.api.listAdmissions).toHaveBeenCalledWith({ property: undefined });
    expect(state.api.listResidents).toHaveBeenCalledWith(undefined);
  });
});

describe("phone Today's Activity", () => {
  const phone = () => within(document.querySelector(".md\\:hidden") as HTMLElement);

  test("lists only what happened on the local calendar day, with an honest empty state otherwise", async () => {
    state.api.listResidents.mockResolvedValue([
      { id: "r1", first_name: "Rahul", last_name: "Sharma", unit: "Room 101" },
      { id: "r2", first_name: "Priya", last_name: "Patel", unit: "Room 102" },
    ]);
    state.api.listAdmissions.mockResolvedValue([
      { id: "a1", resident: "r1", joining_date: localDateKey(new Date()) },
      { id: "a2", resident: "r2", joining_date: daysAgo(3) },
    ]);
    renderWithIntl(<DashboardPage />);

    await waitFor(() => expect(phone().getByText(/Rahul Sharma/)).toBeInTheDocument());
    expect(phone().queryByText(/Priya Patel/)).toBeNull();
  });

  test("shows 'No activity today.' when nothing happened today (older items do not count)", async () => {
    state.api.listResidents.mockResolvedValue([{ id: "r2", first_name: "Priya", last_name: "Patel", unit: "Room 102" }]);
    state.api.listAdmissions.mockResolvedValue([{ id: "a2", resident: "r2", joining_date: daysAgo(3) }]);
    renderWithIntl(<DashboardPage />);

    await waitFor(() => expect(state.api.listAdmissions).toHaveBeenCalled());
    expect(await phone().findByText("No activity today.")).toBeInTheDocument();
  });

  test("does not claim 'No activity today.' while the feed is still loading", async () => {
    state.api.listAdmissions.mockReturnValue(new Promise(() => {})); // never settles
    renderWithIntl(<DashboardPage />);

    await waitFor(() => expect(state.api.listAdmissions).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(phone().queryByText("No activity today.")).toBeNull();
    expect(phone().queryByText("Today's Activity")).toBeNull(); // a skeleton stands in for the card
  });

  test("a failed source shows an error with retry, not a misleading empty or partial feed", async () => {
    state.api.listPaymentsFiltered.mockRejectedValue(new Error("down"));
    renderWithIntl(<DashboardPage />);

    const alerts = await phone().findAllByRole("alert");
    expect(alerts.length).toBeGreaterThan(0);
    expect(phone().queryByText("No activity today.")).toBeNull();

    state.api.listPaymentsFiltered.mockClear();
    state.api.listPaymentsFiltered.mockResolvedValue([]);
    fireEvent.click(within(alerts[alerts.length - 1]).getByRole("button", { name: /retry/i }));
    await waitFor(() => expect(state.api.listPaymentsFiltered).toHaveBeenCalled());
    expect(await phone().findByText("No activity today.")).toBeInTheDocument();
  });

  test("a user who can read none of the activity sources gets no activity card at all", async () => {
    state.permissions = new Set(["view_dashboard"]);
    renderWithIntl(<DashboardPage />);

    await waitFor(() => expect(state.api.getAnalyticsSummary).toHaveBeenCalled());
    expect(phone().queryByText("No activity today.")).toBeNull();
    expect(phone().queryByText("Today's Activity")).toBeNull();
  });
});
