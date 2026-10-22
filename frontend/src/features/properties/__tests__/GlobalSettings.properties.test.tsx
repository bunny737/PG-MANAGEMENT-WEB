/* eslint-disable i18next/no-literal-string -- test fixtures, not UI copy */
import { act, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, test, vi } from "vitest";
import properties from "@/messages/en/properties.json";
import settings from "@/messages/en/settings.json";

const api = vi.hoisted(() => ({ listProperties: vi.fn(), getCurrentUser: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, ...api };
});
vi.mock("@/features/subscription/SubscriptionPanel", () => ({ SubscriptionPanel: () => null }));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));

import { GlobalSettings } from "../GlobalSettings";

const PROPERTY_ID = "7d6c0a52-0f4e-4d0c-9a53-3b1f6a6f7c11";

async function renderSettings() {
  render(
    <NextIntlClientProvider locale="en" messages={{ settings, properties }}>
      <GlobalSettings />
    </NextIntlClientProvider>
  );
  await act(async () => {});
}

describe("Settings → property setup tab", () => {
  beforeEach(() => {
    for (const fn of Object.values(api)) fn.mockReset();
    api.getCurrentUser.mockResolvedValue({});
  });

  test("lists the tenant's real properties with links that carry only real ids", async () => {
    api.listProperties.mockResolvedValue([
      { id: PROPERTY_ID, name: "Sunrise PG", property_type: "pg", city: "Hyderabad", state: "Telangana" },
    ]);
    await renderSettings();

    expect(screen.getByText("Sunrise PG")).toBeTruthy();
    expect(screen.getByText(/PG \(Paying Guest\) · Hyderabad, Telangana/)).toBeTruthy();
    const hrefs = screen.getAllByRole("link").map((link) => link.getAttribute("href"));
    expect(hrefs).toEqual([`/properties/${PROPERTY_ID}/buildings`, `/properties/${PROPERTY_ID}`]);
  });

  test("shows no demo properties and no fake portal form", async () => {
    api.listProperties.mockResolvedValue([]);
    await renderSettings();

    expect(screen.queryByText(/Skyline|Sunset/)).toBeNull();
    expect(screen.queryByText(/StaysManager/i)).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.getByText(properties.list.emptyTitle)).toBeTruthy();
  });

  test("a failed load says so instead of showing anything made up", async () => {
    api.listProperties.mockRejectedValue(new Error("boom"));
    await renderSettings();
    expect(screen.getByRole("alert").textContent).toBe(settings.global.profilesLoadFailed);
    expect(screen.queryByRole("link")).toBeNull();
  });

  test("says it is loading until the list arrives", async () => {
    api.listProperties.mockReturnValue(new Promise(() => {}));
    await renderSettings();
    expect(screen.getByRole("status").textContent).toBe(properties.list.loadingProperties);
  });
});
