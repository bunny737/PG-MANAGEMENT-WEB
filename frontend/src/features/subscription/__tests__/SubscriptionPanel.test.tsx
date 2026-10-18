import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createTranslator, NextIntlClientProvider } from "next-intl";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import commonEn from "@/messages/en/common.json";
import settingsEn from "@/messages/en/settings.json";
import commonTe from "@/messages/te/common.json";
import settingsTe from "@/messages/te/settings.json";
import { SubscriptionPanel } from "../SubscriptionPanel";
import { ApiError, getSubscription, listPlans, selectPlan, type Plan, type Subscription } from "@/lib/api";
import { openSubscriptionCheckout } from "@/lib/razorpay";

const session = vi.hoisted(() => ({
  value: {
    ready: true,
    can: (): boolean => true,
    user: { tenant_id: "t1", tenant: { id: "t1", name: "Sunrise PG" }, first_name: "Ravi", email: "ravi@example.com" },
  },
}));

vi.mock("@/lib/session", () => ({ useSession: () => session.value }));
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, listPlans: vi.fn(), getSubscription: vi.fn(), selectPlan: vi.fn() };
});
vi.mock("@/lib/razorpay", () => ({ openSubscriptionCheckout: vi.fn() }));

const BASIC: Plan = {
  id: "p-basic", name: "Basic", pricing_type: "flat_monthly", max_beds: 500, max_properties: null,
  max_residents_per_property: null, price_per_month: "149.00", bed_tiers: [], is_trial_plan: true, is_active: true,
};
const UNLIMITED: Plan = { ...BASIC, id: "p-unl", name: "Unlimited", max_beds: null, price_per_month: "249.00", is_trial_plan: false };
const PER_BED: Plan = {
  ...BASIC, id: "p-bed", name: "Per Bed", pricing_type: "per_bed_monthly", max_beds: null, price_per_month: null,
  is_trial_plan: false,
  bed_tiers: [
    { id: "a", up_to_beds: 50, rate_per_bed: "0.00" },
    { id: "b", up_to_beds: 200, rate_per_bed: "5.00" },
    { id: "c", up_to_beds: null, rate_per_bed: "3.50" },
  ],
};

const VALUES = { count: 2, date: "1 Jan 2027", plan: "Basic", price: "₹149", used: 3, max: 500, from: 1, to: 50 };

const inDays = (days: number) => new Date(Date.now() + days * 86_400_000).toISOString();

function subscription(overrides: Partial<Subscription> = {}): Subscription {
  return {
    id: "s1", tenant: "t1", plan: null, tenant_status: "trial", trial_ends_at: inDays(30),
    razorpay_subscription_id: "", pending_plan: null, pending_razorpay_subscription_id: "",
    razorpay_key_id: "rzp_test_key", current_period_end: null,
    bed_count: 12, max_beds: 500, max_properties: null, properties_used: 1, ...overrides,
  };
}

function renderPanel(locale: "en" | "te" = "en") {
  const messages = locale === "en" ? { settings: settingsEn, common: commonEn } : { settings: settingsTe, common: commonTe };
  return render(
    <NextIntlClientProvider locale={locale} messages={messages} onError={() => {}}>
      <SubscriptionPanel />
    </NextIntlClientProvider>,
  );
}

async function renderLoaded(sub: Subscription, plans: Plan[] = [BASIC, UNLIMITED]) {
  vi.mocked(listPlans).mockResolvedValue(plans);
  vi.mocked(getSubscription).mockResolvedValue(sub);
  const view = renderPanel();
  await screen.findByText("Available plans");
  return view;
}

// Plan cards use h4; the current-plan banner (h2) can carry the same name.
const planCard = (name: string) => screen.getByRole("heading", { name, level: 4 }).closest("article") as HTMLElement;

describe("SubscriptionPanel", () => {
  beforeEach(() => {
    vi.mocked(listPlans).mockReset();
    vi.mocked(getSubscription).mockReset();
    vi.mocked(selectPlan).mockReset();
    vi.mocked(openSubscriptionCheckout).mockReset();
    session.value.can = () => true;
  });

  it("shows the trial, bed usage and both plans with their prices and limits", async () => {
    await renderLoaded(subscription());

    expect(screen.getByText("Free trial", { selector: "span" })).toBeTruthy();
    expect(screen.getByText(/30 days left in your free trial/)).toBeTruthy();
    expect(screen.getByText(/the Basic plan's limits/)).toBeTruthy();
    expect(screen.getByText("12 of 500 beds used")).toBeTruthy();
    expect(within(planCard("Basic")).getByText("₹149/month")).toBeTruthy();
    expect(within(planCard("Basic")).getByText("Up to 500 beds")).toBeTruthy();
    expect(within(planCard("Unlimited")).getByText("₹249/month")).toBeTruthy();
    expect(within(planCard("Unlimited")).getByText("Unlimited beds")).toBeTruthy();
  });

  it("disables a plan that is smaller than the tenant's current beds and says why", async () => {
    await renderLoaded(subscription({ plan: UNLIMITED, tenant_status: "active", bed_count: 600, max_beds: null }));

    const basic = within(planCard("Basic"));
    expect(basic.getByText("You have 600 beds, but this plan allows 500.")).toBeTruthy();
    expect(basic.getByRole("button")).toHaveProperty("disabled", true);
    expect(within(planCard("Unlimited")).getByRole("button", { name: "Current plan" })).toHaveProperty("disabled", true);
  });

  it("says the trial has ended instead of '0 days left' once its end date has passed", async () => {
    await renderLoaded(subscription({ trial_ends_at: inDays(-3) }));

    expect(screen.getByText(/Your free trial ended on/)).toBeTruthy();
    expect(screen.queryByText(/days left in your free trial/)).toBeNull();
  });

  it("warns when close to the bed limit", async () => {
    await renderLoaded(subscription({ bed_count: 460 }));
    expect(screen.getByText(/close to your bed limit/)).toBeTruthy();
  });

  it("selects a flat plan after confirmation, opens Razorpay Checkout and reports activation", async () => {
    const pending = subscription({ pending_plan: UNLIMITED, pending_razorpay_subscription_id: "sub_123" });
    vi.mocked(selectPlan).mockResolvedValue(pending);
    vi.mocked(openSubscriptionCheckout).mockResolvedValue("paid");
    await renderLoaded(subscription());
    vi.mocked(getSubscription).mockResolvedValue({
      ...pending, plan: UNLIMITED, pending_plan: null, pending_razorpay_subscription_id: "", razorpay_subscription_id: "sub_123",
      tenant_status: "active", max_beds: null, current_period_end: inDays(30),
    });

    fireEvent.click(within(planCard("Unlimited")).getByRole("button", { name: "Choose plan" }));
    expect(screen.getByText(/Switch to the Unlimited plan at ₹249 a month/)).toBeTruthy();
    expect(selectPlan).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    expect(await screen.findByText("Your plan is active.")).toBeTruthy();
    expect(selectPlan).toHaveBeenCalledWith("t1", "p-unl");
    expect(openSubscriptionCheckout).toHaveBeenCalledWith(
      expect.objectContaining({ keyId: "rzp_test_key", subscriptionId: "sub_123", businessName: "Sunrise PG" }),
    );
  });

  it("keeps the paying tenant on its current plan, and does not call a still-active tenant upgraded, until the new plan is paid", async () => {
    const active = subscription({ plan: BASIC, tenant_status: "active", razorpay_subscription_id: "sub_basic", current_period_end: inDays(20) });
    const switching = { ...active, pending_plan: UNLIMITED, pending_razorpay_subscription_id: "sub_new" };
    vi.mocked(selectPlan).mockResolvedValue(switching);
    vi.mocked(openSubscriptionCheckout).mockResolvedValue("paid");
    await renderLoaded(active);
    // The webhook hasn't landed yet: the tenant is "active" but still on Basic with the switch pending.
    vi.mocked(getSubscription).mockResolvedValue(switching);

    fireEvent.click(within(planCard("Unlimited")).getByRole("button", { name: "Choose plan" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    expect(await screen.findByText(/Payment received. Activating your plan/)).toBeTruthy();
    await waitFor(() => expect(getSubscription).toHaveBeenCalledTimes(2)); // initial load + first poll
    expect(screen.queryByText("Your plan is active.")).toBeNull();
    expect(screen.getByRole("heading", { name: "Basic", level: 2 })).toBeTruthy(); // still Basic
    expect(screen.getByText("Payment pending")).toBeTruthy();
    expect(within(planCard("Basic")).getByRole("button", { name: "Current plan" })).toHaveProperty("disabled", true);
  });

  it("does not open Checkout when payments are not configured", async () => {
    vi.mocked(selectPlan).mockResolvedValue(subscription({ pending_plan: UNLIMITED, pending_razorpay_subscription_id: "test_sub_1", razorpay_key_id: "" }));
    await renderLoaded(subscription());

    fireEvent.click(within(planCard("Unlimited")).getByRole("button", { name: "Choose plan" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    expect(await screen.findByText(/Online payment isn.t set up/)).toBeTruthy();
    expect(openSubscriptionCheckout).not.toHaveBeenCalled();
  });

  it("tells the owner when they close Checkout without paying, and lets them pay later", async () => {
    const pending = subscription({ pending_plan: UNLIMITED, pending_razorpay_subscription_id: "sub_123" });
    vi.mocked(selectPlan).mockResolvedValue(pending);
    vi.mocked(openSubscriptionCheckout).mockResolvedValue("dismissed");
    await renderLoaded(subscription());

    fireEvent.click(within(planCard("Unlimited")).getByRole("button", { name: "Choose plan" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    expect(await screen.findByText(/Payment wasn't completed/)).toBeTruthy();
    expect(screen.getByText("Payment pending")).toBeTruthy();

    vi.mocked(openSubscriptionCheckout).mockResolvedValue("dismissed");
    fireEvent.click(screen.getByRole("button", { name: "Pay now" }));
    await waitFor(() => expect(openSubscriptionCheckout).toHaveBeenCalledTimes(2));
  });

  it("shows the server's message and opens no Checkout when the plan is refused", async () => {
    const message = "You have 600 beds, but this plan allows 500. Remove beds or choose a larger plan.";
    vi.mocked(selectPlan).mockRejectedValue(new ApiError(400, { detail: message, code: "PLAN_BED_LIMIT_EXCEEDED" }));
    await renderLoaded(subscription());

    fireEvent.click(within(planCard("Basic")).getByRole("button", { name: "Choose plan" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    expect(await screen.findByText(message)).toBeTruthy();
    expect(openSubscriptionCheckout).not.toHaveBeenCalled();
  });

  it("lists a per-bed plan's price steps and activates it without Checkout", async () => {
    vi.mocked(selectPlan).mockResolvedValue(subscription({ plan: PER_BED, tenant_status: "active", max_beds: null }));
    await renderLoaded(subscription(), [BASIC, PER_BED]);

    const card = within(planCard("Per Bed"));
    expect(card.getByText("Beds 1-50: Free")).toBeTruthy();
    expect(card.getByText("Beds 51-200: ₹5 per bed")).toBeTruthy();
    expect(card.getByText("Beds 201 and above: ₹3.5 per bed")).toBeTruthy();

    fireEvent.click(card.getByRole("button", { name: "Choose plan" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    expect(await screen.findByText("You're now on the Per Bed plan.")).toBeTruthy();
    expect(openSubscriptionCheckout).not.toHaveBeenCalled();
  });

  it("is owner-only and makes no API calls for anyone else", async () => {
    session.value.can = () => false;
    renderPanel();

    expect(await screen.findByText("Only the account owner can manage the plan and billing.")).toBeTruthy();
    expect(listPlans).not.toHaveBeenCalled();
    expect(getSubscription).not.toHaveBeenCalled();
  });

  it("offers a retry when the plan cannot be loaded", async () => {
    vi.mocked(listPlans).mockRejectedValueOnce(new ApiError(500, { detail: "boom" })).mockResolvedValue([BASIC, UNLIMITED]);
    vi.mocked(getSubscription).mockResolvedValue(subscription());
    renderPanel();

    fireEvent.click(await screen.findByRole("button", { name: "Try again" }));

    expect(await screen.findByText("Available plans")).toBeTruthy();
  });

  it("has a well-formed Telugu string for every English key", () => {
    expect(Object.keys(settingsTe.subscription).sort()).toEqual(Object.keys(settingsEn.subscription).sort());

    for (const [locale, settings, common] of [["en", settingsEn, commonEn], ["te", settingsTe, commonTe]] as const) {
      const errors: unknown[] = [];
      const translate = createTranslator({
        locale, messages: { settings, common }, namespace: "settings.subscription", onError: (error) => errors.push(error),
      });
      for (const key of Object.keys(settings.subscription)) {
        const text = (translate as unknown as (key: string, values: typeof VALUES) => string)(key, VALUES);
        expect(text, `${locale}.${key}`).not.toContain("settings.subscription");
      }
      expect(errors, locale).toEqual([]);
    }
  });

  it("renders every string in Telugu with no missing message keys", async () => {
    vi.mocked(listPlans).mockResolvedValue([BASIC, UNLIMITED, PER_BED]);
    vi.mocked(getSubscription).mockResolvedValue(subscription({ plan: BASIC, pending_plan: UNLIMITED, pending_razorpay_subscription_id: "sub_1" }));
    const { container } = renderPanel("te");

    await waitFor(() => expect(container.querySelector("article")).not.toBeNull());
    expect(container.textContent).not.toContain("settings.subscription");
    expect(container.textContent).toContain("అపరిమిత బెడ్‌లు");
  });
});
