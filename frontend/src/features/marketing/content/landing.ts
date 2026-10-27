// The keyword-targeted solution pages (docs/seo/keyword-map.md). Single source for the routes,
// the sitemap, the footer and the hub; copy lives in messages/<locale>/marketing.json under
// `solutions.pages.<slug>`. A page may only list features that are `available` on the owner web
// (content.test.ts / landing.test.ts enforce it), so the copy cannot overclaim (frontend-plan §12.5).

export const SOLUTION_SLUGS = ["pg-rent-tracking", "hostel-management-software", "pg-bed-occupancy"] as const;
export type SolutionSlug = (typeof SOLUTION_SLUGS)[number];

export interface SolutionPage {
  slug: SolutionSlug;
  /** Sitemap lastmod (YYYY-MM-DD). Bump only for a significant content, schema or link change. */
  lastReviewed: string;
  /** Keys into content/features.ts, in display order. */
  featureKeys: readonly string[];
  /** The one query cluster this page owns (docs/seo/keyword-map.md). */
  cluster: string;
}

export const SOLUTION_PAGES: readonly SolutionPage[] = [
  {
    slug: "pg-rent-tracking",
    lastReviewed: "2026-10-25",
    featureKeys: ["billing", "payments", "discounts", "expenses", "reports"],
    cluster: "PG rent management app",
  },
  {
    slug: "hostel-management-software",
    lastReviewed: "2026-10-25",
    featureKeys: ["residents", "billing", "payments", "visitors", "staff", "dashboard"],
    cluster: "hostel management software",
  },
  {
    slug: "pg-bed-occupancy",
    lastReviewed: "2026-10-25",
    featureKeys: ["dashboard", "residents", "reports"],
    cluster: "track vacant beds across PG properties",
  },
];

export const SOLUTIONS_HUB_PATH = "/solutions";
/** Hub lastmod floor; the sitemap also follows the newest page below it. */
export const SOLUTIONS_HUB_LAST_REVIEWED = "2026-10-25";

export const solutionPath = (slug: SolutionSlug) => `${SOLUTIONS_HUB_PATH}/${slug}`;

export function findSolution(slug: string): SolutionPage | undefined {
  return SOLUTION_PAGES.find((page) => page.slug === slug);
}
