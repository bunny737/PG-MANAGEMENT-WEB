/* eslint-disable i18next/no-literal-string -- test fixtures, not UI copy */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, test, vi } from "vitest";
import common from "@/messages/en/common.json";
import settings from "@/messages/en/settings.json";

const api = vi.hoisted(() => ({
  getProperty: vi.fn(),
  getPropertySettings: vi.fn(),
  updatePropertySettings: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, ...api };
});
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));

import { PropertySettingsForm } from "../PropertySettingsForm";

const PROPERTY_ID = "7d6c0a52-0f4e-4d0c-9a53-3b1f6a6f7c11";
const copy = settings.propertySettings;

const SETTINGS = {
  id: "s1",
  room_transfer_rent_timing: "next_billing_cycle",
  late_payment_penalty_type: "none",
  penalty_value: null,
  penalty_grace_days: 5,
  penalty_applies_to: "full_invoice",
  penalty_compounding: "one_time",
  auto_billing_enabled: true,
  billing_day_rule: "admission_date",
  billing_day_of_month: null,
  food_charge_per_day: "100.00" as string | null,
  created_at: "",
  updated_at: "",
};

async function renderForm() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale="en" messages={{ common, settings }}>
        <PropertySettingsForm propertyId={PROPERTY_ID} />
      </NextIntlClientProvider>
    </QueryClientProvider>
  );
  await screen.findByRole("heading", { name: copy.title });
}

const field = () => screen.getByLabelText(copy.foodChargeLabel) as HTMLInputElement;

async function save() {
  fireEvent.click(screen.getByRole("button", { name: copy.save }));
  await act(async () => {});
}

describe("Property settings → food charge per day (Module 24)", () => {
  beforeEach(() => {
    for (const fn of Object.values(api)) fn.mockReset();
    api.getProperty.mockResolvedValue({ id: PROPERTY_ID, name: "Sunrise PG" });
    api.getPropertySettings.mockResolvedValue(SETTINGS);
    api.updatePropertySettings.mockImplementation(async (_id, payload) => ({ ...SETTINGS, ...payload }));
  });

  test("shows the saved default and saves a changed one", async () => {
    await renderForm();
    expect(field().value).toBe("100.00");

    fireEvent.change(field(), { target: { value: "120" } });
    await save();

    expect(api.updatePropertySettings).toHaveBeenCalledWith(
      PROPERTY_ID,
      expect.objectContaining({ food_charge_per_day: "120" })
    );
  });

  test("clearing it saves null, meaning no default", async () => {
    await renderForm();
    fireEvent.change(field(), { target: { value: "" } });
    await save();

    expect(api.updatePropertySettings).toHaveBeenCalledWith(
      PROPERTY_ID,
      expect.objectContaining({ food_charge_per_day: null })
    );
  });

  test("an amount the API would reject is stopped before saving", async () => {
    await renderForm();
    fireEvent.change(field(), { target: { value: "1000000" } });
    await save();

    expect(screen.getByText(copy.errFoodChargeRange)).toBeTruthy();
    expect(api.updatePropertySettings).not.toHaveBeenCalled();
  });
});
