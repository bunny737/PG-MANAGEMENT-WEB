import type { MetadataRoute } from "next";
import {
  SOLUTION_PAGES,
  SOLUTIONS_HUB_LAST_REVIEWED,
  SOLUTIONS_HUB_PATH,
  solutionPath,
} from "@/features/marketing/content/landing";
import { getPlanCatalog } from "@/features/marketing/data/plans";
import { PAGE_LAST_MODIFIED, PATHS, PRICE_PAGES, type MarketingPage } from "@/features/marketing/seo";
import { resolveLastModified } from "@/features/marketing/seoCore";
import { getSiteConfig } from "@/lib/site-config";

// No changeFrequency / priority: Google ignores both. lastModified is the page's own review date
// (seo.ts, content/landing.ts), or the plan catalogue's updated_at on the pages that show prices
// (the solution pages show a pricing teaser too), and is never "now".
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const { url } = getSiteConfig();
  const catalog = await getPlanCatalog();
  const catalogUpdatedAt = catalog.status === "unavailable" ? null : catalog.data.updated_at;
  const now = new Date();
  const entry = (path: string, reviewed: string, followsCatalogue: boolean) => ({
    url: `${url}${path === "/" ? "" : path}`,
    lastModified: resolveLastModified(reviewed, followsCatalogue ? catalogUpdatedAt : null, now),
  });

  const pages = (Object.keys(PATHS) as MarketingPage[]).map((page) =>
    entry(PATHS[page], PAGE_LAST_MODIFIED[page], PRICE_PAGES.includes(page))
  );
  const newestSolution = SOLUTION_PAGES.map((page) => page.lastReviewed).reduce(
    (latest, date) => (date > latest ? date : latest),
    SOLUTIONS_HUB_LAST_REVIEWED
  );
  return [
    ...pages,
    entry(SOLUTIONS_HUB_PATH, newestSolution, false),
    ...SOLUTION_PAGES.map((page) => entry(solutionPath(page.slug), page.lastReviewed, true)),
  ];
}
