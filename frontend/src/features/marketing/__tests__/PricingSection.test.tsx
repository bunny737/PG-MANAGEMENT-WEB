import { render, screen, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import React from "react";
import { describe, expect, it, vi } from "vitest";

import marketingEn from "@/messages/en/marketing.json";
import marketingTe from "@/messages/te/marketing.json";
import { PricingSection } from "../sections/PricingSection";
import { getPlanCatalog, type PublicPlan } from "../data/plans";

const locale = vi.hoisted(() => ({ value: "en" as "en" | "te" }));

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) =>
    // Loose typing: the real getTranslations narrows `namespace` to the catalogue's keys.
    (createTranslator as (options: object) => unknown)({
      locale: locale.value,
      messages: { marketing: locale.value === "en" ? marketingEn : marketingTe },
      namespace,
    }),
}));
vi.mock("../data/plans", () => ({ getPlanCatalog: vi.fn() }));
vi.mock("../PrimaryCtaButton", () => ({ PrimaryCtaButton: () => <a href="/start">Start</a> }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>{children}</a>
  ),
}));

const BASIC: PublicPlan = {
  id: "p-basic", name: "Basic", pricing_type: "flat_monthly", price_per_month: "199.00",
  max_beds: 500, bed_tiers: [], is_trial_plan: true,
};
const UNLIMITED: PublicPlan = { ...BASIC, id: "p-unl", name: "Unlimited", price_per_month: "299.00", max_beds: null, is_trial_plan: false };
const PER_BED: PublicPlan = {
  ...BASIC, id: "p-bed", name: "Per Bed", pricing_type: "per_bed_monthly", price_per_month: null, max_beds: null,
  is_trial_plan: false, bed_tiers: [{ up_to_beds: null, rate_per_bed: "3.50" }],
};

async function renderPricing(plans: PublicPlan[], lang: "en" | "te" = "en") {
  locale.value = lang;
  vi.mocked(getPlanCatalog).mockResolvedValue({
    status: "ok",
    data: { currency: "INR", trial_days: 45, updated_at: null, plans },
  } as Awaited<ReturnType<typeof getPlanCatalog>>);
  return render(await PricingSection({ variant: "full" }));
}

const planCard = (name: string) => screen.getByRole("heading", { name, level: 3 }).closest("li") as HTMLElement;

describe("PricingSection", () => {
  it("shows each flat plan's price, bed cap and the shared feature list", async () => {
    await renderPricing([BASIC, UNLIMITED]);

    const basic = within(planCard("Basic"));
    expect(basic.getByText("₹199.00")).toBeTruthy();
    expect(basic.getByText("Up to 500 beds")).toBeTruthy();
    const unlimited = within(planCard("Unlimited"));
    expect(unlimited.getByText("₹299.00")).toBeTruthy();
    expect(unlimited.getByText("Unlimited beds")).toBeTruthy();

    for (const card of [basic, unlimited]) {
      expect(card.getByText("Unlimited properties")).toBeTruthy();
      expect(card.getByText("Unlimited rooms")).toBeTruthy();
      expect(card.getByText("Free public listing for your PG")).toBeTruthy();
    }
  });

  it("does not show the flat-plan feature list on a per-bed plan", async () => {
    await renderPricing([PER_BED]);

    expect(within(planCard("Per Bed")).queryByText("Unlimited properties")).toBeNull();
  });

  it("renders the feature list in Telugu", async () => {
    await renderPricing([BASIC], "te");

    expect(within(planCard("Basic")).getByText(marketingTe.pricing.features.properties)).toBeTruthy();
  });

  it("explains pricing is unavailable instead of showing baked-in prices", async () => {
    locale.value = "en";
    vi.mocked(getPlanCatalog).mockResolvedValue({ status: "unavailable" } as Awaited<ReturnType<typeof getPlanCatalog>>);
    render(await PricingSection({ variant: "full" }));

    expect(screen.getByText("Pricing is temporarily unavailable")).toBeTruthy();
    expect(screen.queryByText("Unlimited properties")).toBeNull();
  });
});
