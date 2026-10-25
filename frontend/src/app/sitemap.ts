import type { MetadataRoute } from "next";
import { getPlanCatalog } from "@/features/marketing/data/plans";
import { PAGE_LAST_MODIFIED, PATHS, PRICE_PAGES, type MarketingPage } from "@/features/marketing/seo";
import { resolveLastModified } from "@/features/marketing/seoCore";
import { getSiteConfig } from "@/lib/site-config";

// No changeFrequency / priority: Google ignores both. lastModified is the page's own review date
// (seo.ts), or the plan catalogue's updated_at on the pages that show prices, and is never "now".
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const { url } = getSiteConfig();
  const catalog = await getPlanCatalog();
  const catalogUpdatedAt = catalog.status === "unavailable" ? null : catalog.data.updated_at;
  const now = new Date();

  return (Object.keys(PATHS) as MarketingPage[]).map((page) => ({
    url: `${url}${PATHS[page] === "/" ? "" : PATHS[page]}`,
    lastModified: resolveLastModified(
      PAGE_LAST_MODIFIED[page],
      PRICE_PAGES.includes(page) ? catalogUpdatedAt : null,
      now
    ),
  }));
}
