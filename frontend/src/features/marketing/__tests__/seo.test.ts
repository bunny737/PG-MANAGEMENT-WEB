import { afterEach, describe, expect, it, vi } from "vitest";
import {
  OG_LOCALE,
  SOCIAL_IMAGE,
  breadcrumbJsonLd,
  pageMetadata,
  resolveLastModified,
  softwareApplicationJsonLd,
  websiteJsonLd,
} from "../seoCore";

describe("pageMetadata", () => {
  const meta = pageMetadata({
    title: "Pricing — PGLive",
    description: "Simple monthly plans.",
    path: "/pricing",
    siteName: "PGLive",
  });

  it("sets the canonical path", () => {
    expect(meta.alternates?.canonical).toBe("/pricing");
  });

  // Next merges metadata shallowly, so a page-level object must stand on its own.
  it("emits a complete openGraph object", () => {
    expect(meta.openGraph).toMatchObject({
      type: "website",
      siteName: "PGLive",
      locale: OG_LOCALE,
      title: "Pricing — PGLive",
      description: "Simple monthly plans.",
      url: "/pricing",
      images: [SOCIAL_IMAGE],
    });
  });

  it("emits a complete twitter object", () => {
    expect(meta.twitter).toMatchObject({
      card: "summary_large_image",
      images: [{ url: SOCIAL_IMAGE.url, alt: SOCIAL_IMAGE.alt }],
      title: "Pricing — PGLive",
      description: "Simple monthly plans.",
    });
  });
});

describe("structured data", () => {
  it("builds a positioned breadcrumb trail with absolute URLs", () => {
    const data = breadcrumbJsonLd("https://www.pglive.in", [
      { name: "Home", path: "/" },
      { name: "Pricing", path: "/pricing" },
    ]);
    expect(data["@type"]).toBe("BreadcrumbList");
    expect(data.itemListElement).toEqual([
      { "@type": "ListItem", position: 1, name: "Home", item: "https://www.pglive.in" },
      { "@type": "ListItem", position: 2, name: "Pricing", item: "https://www.pglive.in/pricing" },
    ]);
  });

  it("builds a WebSite entry", () => {
    expect(websiteJsonLd("https://www.pglive.in", "PGLive")).toMatchObject({
      "@type": "WebSite",
      name: "PGLive",
      url: "https://www.pglive.in",
    });
  });

  it("names Android before launch but adds downloadUrl only when the listing is live", () => {
    const base = { origin: "https://www.pglive.in", name: "PGLive", offers: [] };
    const soon = softwareApplicationJsonLd({ ...base, playStoreUrl: null });
    expect(soon.operatingSystem).toBe("Web, Android");
    expect(soon).not.toHaveProperty("downloadUrl");
    expect(soon).not.toHaveProperty("offers");

    const live = softwareApplicationJsonLd({
      ...base,
      playStoreUrl: "https://play.google.com/store/apps/details?id=in.pglive",
    });
    expect(live.downloadUrl).toBe("https://play.google.com/store/apps/details?id=in.pglive");
  });

  it("never invents ratings or reviews", () => {
    const data = softwareApplicationJsonLd({
      origin: "https://www.pglive.in",
      name: "PGLive",
      offers: [{ "@type": "Offer", name: "Starter", price: "999.00", priceCurrency: "INR" }],
      playStoreUrl: null,
    });
    expect(data).not.toHaveProperty("aggregateRating");
    expect(data).not.toHaveProperty("review");
    expect(data.offers).toHaveLength(1);
  });
});

describe("resolveLastModified", () => {
  const now = new Date("2026-11-01T00:00:00Z");

  it("uses the page date when there is no catalogue date", () => {
    expect(resolveLastModified("2026-10-25", null, now).toISOString()).toBe("2026-10-25T00:00:00.000Z");
    expect(resolveLastModified("2026-10-25", undefined, now).toISOString()).toBe("2026-10-25T00:00:00.000Z");
  });

  it("follows a newer catalogue date", () => {
    expect(resolveLastModified("2026-10-25", "2026-10-30T09:00:00Z", now).toISOString()).toBe(
      "2026-10-30T09:00:00.000Z"
    );
  });

  it("ignores an older, unparsable or future catalogue date", () => {
    for (const bad of ["2026-09-01T00:00:00Z", "not a date", "2027-01-01T00:00:00Z"]) {
      expect(resolveLastModified("2026-10-25", bad, now).toISOString()).toBe("2026-10-25T00:00:00.000Z");
    }
  });
});

describe("sitemap", () => {
  afterEach(() => vi.useRealTimers());

  async function load(catalog: unknown) {
    vi.resetModules();
    vi.doMock("@/features/marketing/data/plans", () => ({ getPlanCatalog: async () => catalog }));
    vi.doMock("@/lib/site-config", () => ({ getSiteConfig: () => ({ url: "https://www.pglive.in" }) }));
    const { default: sitemap } = await import("@/app/sitemap");
    const seo = await import("../seo");
    return { entries: await sitemap(), seo };
  }

  it("lists every marketing page with an absolute URL and no priority or changeFrequency", async () => {
    const { entries, seo } = await load({ status: "unavailable" });
    expect(entries).toHaveLength(Object.keys(seo.PATHS).length);
    for (const path of seo.MARKETING_PATHS) {
      const url = `https://www.pglive.in${path === "/" ? "" : path}`;
      expect(entries.map((e) => e.url)).toContain(url);
    }
    for (const entry of entries) {
      expect(entry).not.toHaveProperty("priority");
      expect(entry).not.toHaveProperty("changeFrequency");
    }
  });

  it("falls back to each page's own date when the catalogue is unavailable", async () => {
    const { entries, seo } = await load({ status: "unavailable" });
    const pricing = entries.find((e) => e.url.endsWith("/pricing"));
    expect(new Date(pricing!.lastModified as Date).toISOString().slice(0, 10)).toBe(
      seo.PAGE_LAST_MODIFIED.pricing
    );
  });

  it("moves only the price pages when the catalogue changes", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-01T00:00:00Z"));
    const { entries, seo } = await load({
      status: "ok",
      data: { updated_at: "2026-10-31T00:00:00Z", plans: [], currency: "INR", trial_days: 30 },
    });
    const by = (suffix: string) => entries.find((e) => e.url.endsWith(suffix))!.lastModified as Date;
    expect(by("/pricing").toISOString()).toBe("2026-10-31T00:00:00.000Z");
    expect(by("pglive.in").toISOString()).toBe("2026-10-31T00:00:00.000Z");
    expect(by("/contact").toISOString().slice(0, 10)).toBe(seo.PAGE_LAST_MODIFIED.contact);
  });
});
