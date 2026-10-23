import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { onlineManager } from "@tanstack/react-query";
import { BottomNav } from "@/components/shared/BottomNav";
import { OfflineBanner } from "@/components/shared/OfflineBanner";
import { renderWithIntl } from "@/test-utils/renderWithIntl";
import { Fab } from "../Fab";
import { PropertyPill } from "../PropertyPill";
import { StatusBadge, statusBadgeStyle } from "../StatusBadge";

const state = vi.hoisted(() => ({
  permissions: new Set<string>(),
  pathname: "/dashboard",
  propertyId: null as string | null,
  setPropertyId: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => state.pathname,
  useRouter: () => ({ push: vi.fn(), back: vi.fn() }),
}));

vi.mock("@/lib/session", () => ({
  useSession: () => ({ ready: true, authenticated: true, can: (code: string) => state.permissions.has(code) }),
}));

vi.mock("@/components/shared/PropertyFilter", () => ({
  useActiveProperty: () => ({
    propertyId: state.propertyId,
    properties: [
      { id: "p1", name: "Greenwood Girls Hostel" },
      { id: "p2", name: "Keshav PG" },
    ],
    listLoaded: true,
    accessRevoked: false,
    setPropertyId: state.setPropertyId,
  }),
}));

beforeEach(() => {
  state.permissions = new Set(["view_dashboard", "view_property_features", "view_resident_profile", "manage_visitors", "view_finance"]);
  state.pathname = "/dashboard";
  state.propertyId = null;
  state.setPropertyId.mockClear();
});

describe("BottomNav (phone)", () => {
  test("shows Dashboard, Properties, Residents, Billing and More for an owner, in that order (Visitors is not on the bar)", () => {
    renderWithIntl(<BottomNav />);
    const labels = screen.getAllByRole("link").map((link) => link.textContent);
    expect(labels).toEqual(["Dashboard", "Properties", "Residents", "Billing", "More"]);
  });

  test("hides Billing without view_finance, rather than leaving a dead tab", () => {
    state.permissions.delete("view_finance");
    renderWithIntl(<BottomNav />);
    const labels = screen.getAllByRole("link").map((link) => link.textContent);
    expect(labels).toEqual(["Dashboard", "Properties", "Residents", "More"]);
  });

  test("marks the current tab, including on a nested route", () => {
    state.pathname = "/residents/abc";
    renderWithIntl(<BottomNav />);
    expect(screen.getByRole("link", { name: "Residents" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Dashboard" })).not.toHaveAttribute("aria-current");
  });

  test("a route that merely starts with a tab's path is not that tab", () => {
    state.pathname = "/residents-archive";
    renderWithIntl(<BottomNav />);
    expect(screen.getByRole("link", { name: "Residents" })).not.toHaveAttribute("aria-current");
  });
});

describe("StatusBadge", () => {
  test("inquiry is the tertiary (lavender) colour, not the warn colour the desktop pill uses", () => {
    expect(statusBadgeStyle("inquiry")).toContain("bg-m3-tertiary-container");
    expect(statusBadgeStyle("inquiry")).not.toContain("warn");
  });

  test("active is green, notice period is orange, unknown statuses are neutral", () => {
    expect(statusBadgeStyle("active")).toContain("e2ede5");
    expect(statusBadgeStyle("notice_period")).toContain("fdecd2");
    expect(statusBadgeStyle("something_new")).toContain("surface-container-high");
  });

  test("renders its label", () => {
    render(<StatusBadge status="active" label="Active" />);
    expect(screen.getByText("Active")).toBeInTheDocument();
  });
});

describe("PropertyPill", () => {
  test("is a real, named, keyboard-focusable select listing All plus each property", () => {
    renderWithIntl(<PropertyPill />);
    const select = screen.getByRole("combobox", { name: "Property" });
    expect(Array.from(select.querySelectorAll("option")).map((o) => o.textContent)).toEqual([
      "All properties",
      "Greenwood Girls Hostel",
      "Keshav PG",
    ]);
    // Overlaid and transparent, not display:none, so it still takes focus and the tap.
    expect(select.className).toContain("opacity-0");
    expect(select.className).toContain("absolute");
  });

  test("shows All properties until one is picked, and the picked name afterwards", () => {
    renderWithIntl(<PropertyPill />);
    expect(screen.getAllByText("All properties").length).toBeGreaterThan(0);
  });

  test("shows the selected property's name in the pill", () => {
    state.propertyId = "p2";
    renderWithIntl(<PropertyPill />);
    expect(screen.getByText("Keshav PG", { selector: "span" })).toBeInTheDocument();
  });

  test("choosing a property writes it to the shared store; choosing All clears it", () => {
    renderWithIntl(<PropertyPill />);
    const select = screen.getByRole("combobox", { name: "Property" });
    fireEvent.change(select, { target: { value: "p1" } });
    expect(state.setPropertyId).toHaveBeenLastCalledWith("p1");
    fireEvent.change(select, { target: { value: "" } });
    expect(state.setPropertyId).toHaveBeenLastCalledWith(null);
  });
});

describe("Fab", () => {
  test("publishes --fab-stack while mounted so the update toast clears it, and removes it on unmount", () => {
    const { unmount } = render(<Fab href="/x" label="Add" icon={<span />} />);
    expect(document.documentElement.style.getPropertyValue("--fab-stack")).toBe("4.5rem");
    unmount();
    expect(document.documentElement.style.getPropertyValue("--fab-stack")).toBe("");
  });

  test("is a link with its label", () => {
    render(<Fab href="/admissions" label="Admit Resident" icon={<span />} />);
    expect(screen.getByRole("link", { name: "Admit Resident" })).toHaveAttribute("href", "/admissions");
  });
});

describe("OfflineBanner stacking with the phone top bar", () => {
  afterEach(() => {
    act(() => onlineManager.setOnline(true));
    vi.restoreAllMocks();
  });

  test("publishes its measured height as --banner-h while offline so the sticky top bar sits below it", () => {
    // jsdom has no layout: stand in for a banner that wrapped to two lines.
    vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(52);
    renderWithIntl(<OfflineBanner />);
    expect(document.documentElement.style.getPropertyValue("--banner-h")).toBe("");

    act(() => onlineManager.setOnline(false));
    expect(document.documentElement.style.getPropertyValue("--banner-h")).toBe("52px");

    act(() => onlineManager.setOnline(true));
    expect(document.documentElement.style.getPropertyValue("--banner-h")).toBe("");
  });
});
