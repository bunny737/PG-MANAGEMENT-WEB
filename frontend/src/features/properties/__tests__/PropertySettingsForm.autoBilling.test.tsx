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

describe("Property settings → automatic billing", () => {
  beforeEach(() => {
    for (const fn of Object.values(api)) fn.mockReset();
    api.getProperty.mockResolvedValue({ id: PROPERTY_ID, name: "Sunrise PG" });
    api.getPropertySettings.mockResolvedValue(SETTINGS);
    api.updatePropertySettings.mockImplementation(async (_id, payload) => ({ ...SETTINGS, ...payload }));
  });

  test("is on by default, billing on the admission date, with the due date explained", async () => {
    await renderForm();

    expect((screen.getByLabelText(new RegExp(copy.autoBillingToggle)) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByRole("radio", { name: new RegExp(copy.admissionDateTitle) }) as HTMLInputElement).checked).toBe(
      true
    );
    expect(screen.getByText(/due 5 days after the billing day/)).toBeTruthy();
  });

  test("a fixed day must be chosen before anything is saved", async () => {
    // Out-of-range values are already blocked by the input's own min/max.
    await renderForm();
    fireEvent.click(screen.getByRole("radio", { name: new RegExp(copy.fixedDayTitle) }));
    fireEvent.change(screen.getByLabelText(copy.dayOfMonthLabel), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: copy.save }));
    await act(async () => {});

    expect(screen.getByText(copy.errDayOfMonthRange)).toBeTruthy();
    expect(api.updatePropertySettings).not.toHaveBeenCalled();
  });

  test("saves the chosen rule and day", async () => {
    await renderForm();
    fireEvent.click(screen.getByRole("radio", { name: new RegExp(copy.fixedDayTitle) }));
    fireEvent.change(screen.getByLabelText(copy.dayOfMonthLabel), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: copy.save }));
    await act(async () => {});

    expect(api.updatePropertySettings).toHaveBeenCalledWith(
      PROPERTY_ID,
      expect.objectContaining({ auto_billing_enabled: true, billing_day_rule: "fixed_day", billing_day_of_month: 1 })
    );
  });

  test("switching it off hides the billing-day choice and saves it off", async () => {
    await renderForm();
    fireEvent.click(screen.getByLabelText(new RegExp(copy.autoBillingToggle)));

    expect(screen.queryByRole("radio", { name: new RegExp(copy.fixedDayTitle) })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: copy.save }));
    await act(async () => {});
    expect(api.updatePropertySettings).toHaveBeenCalledWith(
      PROPERTY_ID,
      expect.objectContaining({ auto_billing_enabled: false, billing_day_of_month: null })
    );
  });
});
