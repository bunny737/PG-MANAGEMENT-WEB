import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import type { Property } from "@/lib/api";
import { renderWithIntl } from "@/test-utils/renderWithIntl";
import { GlobalSettings } from "../GlobalSettings";

const api = vi.hoisted(() => ({ listProperties: vi.fn(), getCurrentUser: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));
vi.mock("@/features/subscription/SubscriptionPanel", () => ({ SubscriptionPanel: () => null }));

const property = (id: string, name: string): Property =>
  ({ id, name, city: "Hyderabad", state: "Telangana", property_type: "pg" }) as unknown as Property;

beforeEach(() => {
  api.getCurrentUser.mockResolvedValue({ tenant: { default_language: "en", fiscal_year_start_month: 4 } });
});

describe("GlobalSettings property setup tab", () => {
  test("lists the account's own properties and links to their real ids", async () => {
    api.listProperties.mockResolvedValue([property("0b9c1a52-1111-4222-8333-444455556666", "Keshav PG")]);
    renderWithIntl(<GlobalSettings />);

    expect(await screen.findByText("Keshav PG")).toBeInTheDocument();
    expect(screen.getAllByRole("link").map((a) => a.getAttribute("href"))).toContain(
      "/properties/0b9c1a52-1111-4222-8333-444455556666/settings"
    );
  });

  test("a new owner with no properties sees an empty state, not demo properties", async () => {
    api.listProperties.mockResolvedValue([]);
    renderWithIntl(<GlobalSettings />);

    expect(await screen.findByText(/haven't added a property yet/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Add property" })).toHaveAttribute("href", "/properties/add");
    expect(screen.queryByText("Skyline Tower")).not.toBeInTheDocument();
    expect(screen.queryByText("Sunset Apartments Complex")).not.toBeInTheDocument();
  });
});
