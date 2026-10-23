import { cache } from "react";
import { z } from "zod";
import { fetchPublic } from "./publicFetch";

// Mirrors GET /api/v1/public/plans/ (docs/modules/13-subscription.md, "Public
// plan catalogue"). Decimal fields arrive as strings and are kept as strings
// (invariant 5) — display goes through formatMoney.
const bedTierSchema = z.object({
  up_to_beds: z.number().int().nullable(),
  rate_per_bed: z.string(),
});

const planSchema = z
  .object({
    id: z.string(),
    name: z.string().min(1),
    pricing_type: z.enum(["flat_monthly", "per_bed_monthly"]),
    price_per_month: z.string().nullable(),
    max_beds: z.number().int().nullable(),
    bed_tiers: z.array(bedTierSchema),
    is_trial_plan: z.boolean(),
  })
  .refine((plan) => plan.pricing_type !== "flat_monthly" || plan.price_per_month !== null, {
    message: "flat plan without a price",
  })
  .refine((plan) => plan.pricing_type !== "per_bed_monthly" || plan.bed_tiers.length > 0, {
    message: "per-bed plan without tiers",
  });

export const planCatalogSchema = z.object({
  currency: z.string().min(1),
  trial_days: z.number().int().positive(),
  updated_at: z.string().nullable(),
  plans: z.array(planSchema),
});

export type PublicPlan = z.infer<typeof planSchema>;
export type PlanCatalog = z.infer<typeof planCatalogSchema>;

/** Per request de-duplicated: the pricing teaser, pricing page and JSON-LD share one call. */
export const getPlanCatalog = cache(async () => {
  const result = await fetchPublic("/api/v1/public/plans/", planCatalogSchema);
  // An empty catalogue has nothing to show; treat it like an outage rather than render a blank grid.
  if ((result.status === "ok" || result.status === "stale") && result.data.plans.length === 0) {
    return { status: "unavailable" } as const;
  }
  return result;
});
