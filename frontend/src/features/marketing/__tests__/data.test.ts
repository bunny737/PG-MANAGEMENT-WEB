import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchPublic, resetPublicFetchCache } from "../data/publicFetch";
import { planCatalogSchema } from "../data/plans";
import { formatPhone, hasContactInfo, supportSchema, telHref } from "../data/support";

const FLAT = {
  id: "p1",
  name: "Basic",
  pricing_type: "flat_monthly",
  price_per_month: "149.00",
  max_beds: 500,
  bed_tiers: [],
  is_trial_plan: true,
};
const CATALOG = { currency: "INR", trial_days: 45, updated_at: null, plans: [FLAT] };

function respond(body: unknown, ok = true) {
  return Promise.resolve({ ok, status: ok ? 200 : 500, json: () => Promise.resolve(body) } as Response);
}

describe("planCatalogSchema", () => {
  it("accepts the API contract and keeps decimals as strings", () => {
    const parsed = planCatalogSchema.parse(CATALOG);
    expect(parsed.plans[0].price_per_month).toBe("149.00");
    expect(parsed.trial_days).toBe(45);
  });

  it("accepts a per-bed plan with tiers", () => {
    const perBed = {
      ...FLAT,
      id: "p2",
      name: "Per-Bed",
      pricing_type: "per_bed_monthly",
      price_per_month: null,
      max_beds: null,
      is_trial_plan: false,
      bed_tiers: [
        { up_to_beds: 50, rate_per_bed: "0.00" },
        { up_to_beds: null, rate_per_bed: "2.00" },
      ],
    };
    expect(planCatalogSchema.safeParse({ ...CATALOG, plans: [perBed] }).success).toBe(true);
  });

  it("rejects payloads that would make us show a wrong price", () => {
    expect(planCatalogSchema.safeParse({ ...CATALOG, plans: [{ ...FLAT, price_per_month: null }] }).success).toBe(false);
    expect(
      planCatalogSchema.safeParse({
        ...CATALOG,
        plans: [{ ...FLAT, pricing_type: "per_bed_monthly", price_per_month: null, bed_tiers: [] }],
      }).success
    ).toBe(false);
    expect(planCatalogSchema.safeParse({ ...CATALOG, trial_days: "45" }).success).toBe(false);
    expect(planCatalogSchema.safeParse({ currency: "INR" }).success).toBe(false);
  });
});

describe("fetchPublic", () => {
  beforeEach(() => {
    resetPublicFetchCache();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns validated data", async () => {
    vi.stubGlobal("fetch", vi.fn(() => respond(CATALOG)));
    const result = await fetchPublic("/api/v1/public/plans/", planCatalogSchema);
    expect(result.status).toBe("ok");
  });

  it("serves the last good response when the API later fails", async () => {
    const fetchMock = vi.fn().mockImplementationOnce(() => respond(CATALOG)).mockImplementation(() => respond({}, false));
    vi.stubGlobal("fetch", fetchMock);
    await fetchPublic("/api/v1/public/plans/", planCatalogSchema);
    const second = await fetchPublic("/api/v1/public/plans/", planCatalogSchema);
    expect(second.status).toBe("stale");
    if (second.status === "stale") expect(second.data.plans[0].name).toBe("Basic");
  });

  it("is unavailable, never invented, when nothing valid was ever fetched", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("down"))));
    expect((await fetchPublic("/api/v1/public/plans/", planCatalogSchema)).status).toBe("unavailable");
  });

  it("does not accept (or cache) a malformed payload", async () => {
    vi.stubGlobal("fetch", vi.fn(() => respond({ ...CATALOG, plans: [{ ...FLAT, price_per_month: null }] })));
    expect((await fetchPublic("/api/v1/public/plans/", planCatalogSchema)).status).toBe("unavailable");
  });
});

describe("support helpers", () => {
  const empty = { email: null, phone: null, whatsapp: null, whatsapp_url: null, website: null, hours: null };

  it("detects whether there is anything to show on the contact page", () => {
    expect(hasContactInfo(null)).toBe(false);
    expect(hasContactInfo(supportSchema.parse(empty))).toBe(false);
    expect(hasContactInfo({ ...empty, email: "a@b.in" })).toBe(true);
    expect(hasContactInfo({ ...empty, whatsapp_url: "https://wa.me/919876543210" })).toBe(true);
    // website, hours and the company address are shown even when no channel is set
    expect(hasContactInfo({ ...empty, website: "https://help.pglive.in" })).toBe(true);
    expect(hasContactInfo({ ...empty, hours: "Mon-Sat 9-7" })).toBe(true);
    expect(hasContactInfo(null, "12 MG Road, Hyderabad")).toBe(true);
    expect(hasContactInfo(supportSchema.parse(empty), "  ")).toBe(false);
  });

  it("builds tel links and readable Indian numbers", () => {
    expect(telHref("919876543210")).toBe("tel:+919876543210");
    expect(formatPhone("919876543210")).toBe("+91 98765 43210");
    expect(formatPhone("18001234567")).toBe("+18001234567");
  });
});
