import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { getPlanCatalog } from "./data/plans";
import { getSupportContacts } from "./data/support";
import { breadcrumbJsonLd, pageMetadata, softwareApplicationJsonLd, websiteJsonLd } from "./seoCore";
import { SOLUTIONS_HUB_PATH, solutionPath, type SolutionSlug } from "./content/landing";
import { getSiteConfig } from "@/lib/site-config";

export type MarketingPage =
  | "home"
  | "features"
  | "pricing"
  | "app"
  | "contact"
  | "privacy"
  | "terms"
  | "refund"
  | "deleteAccount";

export const PATHS: Record<MarketingPage, string> = {
  home: "/",
  features: "/features",
  pricing: "/pricing",
  app: "/app",
  contact: "/contact",
  privacy: "/privacy",
  terms: "/terms",
  refund: "/refund-policy",
  // Google Play "Delete account URL": public, no sign-in needed to read it.
  deleteAccount: "/delete-account",
};

export const MARKETING_PATHS = Object.values(PATHS);

/** Sitemap `lastmod` per page (YYYY-MM-DD). Bump a date only for a significant change to the
 * page's content, structured data or internal links; the home page also counts as changed when
 * its feature summary changes. Pages in PRICE_PAGES additionally follow the live catalogue's
 * `updated_at` (app/sitemap.ts). */
export const PAGE_LAST_MODIFIED: Record<MarketingPage, string> = {
  home: "2026-10-25",
  features: "2026-10-25",
  pricing: "2026-10-25",
  app: "2026-10-25",
  contact: "2026-10-25",
  privacy: "2026-10-25",
  terms: "2026-10-25",
  refund: "2026-10-25",
  deleteAccount: "2026-10-25",
};

/** Pages that render prices, so a catalogue change is a significant change to them. */
export const PRICE_PAGES: readonly MarketingPage[] = ["home", "pricing"];

// Breadcrumb names reuse the nav / footer labels, so they are already translated everywhere.
const CRUMB_KEYS: Record<Exclude<MarketingPage, "home">, string> = {
  features: "nav.features",
  pricing: "nav.pricing",
  app: "nav.app",
  contact: "nav.contact",
  privacy: "footer.privacy",
  terms: "footer.terms",
  refund: "footer.refund",
  deleteAccount: "footer.deleteAccount",
};

/** Per-page title/description/canonical plus complete OpenGraph and Twitter objects. The locale
 * only changes the text, never the URL, so English is the canonical, indexed version
 * (frontend-plan.md). */
export async function marketingMetadata(page: MarketingPage): Promise<Metadata> {
  const [t, brand] = await Promise.all([
    getTranslations(`marketing.meta.${page}`),
    getTranslations("marketing.brand"),
  ]);
  return pageMetadata({
    title: t("title"),
    description: t("description"),
    path: PATHS[page],
    siteName: brand("name"),
  });
}

/** Home → page BreadcrumbList for every marketing page except the home page. */
export async function breadcrumbForPage(
  page: Exclude<MarketingPage, "home">
): Promise<Record<string, unknown>> {
  const t = await getTranslations("marketing");
  const { url } = getSiteConfig();
  return breadcrumbJsonLd(url, [
    { name: t("brand.name"), path: PATHS.home },
    { name: t(CRUMB_KEYS[page]), path: PATHS[page] },
  ]);
}

/** Organization + WebSite + SoftwareApplication structured data. Offers are built from the
 * live plan catalogue, so they can never disagree with the pricing page. Only flat monthly
 * plans become Offers; per-bed plans have no single price to state. */
export async function organizationJsonLd(): Promise<Record<string, unknown>[]> {
  const [t, support, catalog] = await Promise.all([
    getTranslations("marketing"),
    getSupportContacts(),
    getPlanCatalog(),
  ]);
  const { url, company, playStoreUrl } = getSiteConfig();

  const contactPoint = [
    support?.email ? { "@type": "ContactPoint", contactType: "customer support", email: support.email } : null,
    support?.phone
      ? { "@type": "ContactPoint", contactType: "customer support", telephone: `+${support.phone}` }
      : null,
  ].filter(Boolean);

  const offers =
    catalog.status === "unavailable"
      ? []
      : catalog.data.plans
          .filter((plan) => plan.pricing_type === "flat_monthly" && plan.price_per_month !== null)
          .map((plan) => ({
            "@type": "Offer",
            name: plan.name,
            price: plan.price_per_month,
            priceCurrency: catalog.data.currency,
          }));

  return [
    {
      "@context": "https://schema.org",
      "@type": "Organization",
      name: company.name || t("brand.name"),
      brand: t("brand.name"),
      url,
      logo: `${url}/brand/pglive-mark.png`,
      ...(company.address ? { address: company.address } : {}),
      ...(contactPoint.length ? { contactPoint } : {}),
    },
    websiteJsonLd(url, t("brand.name")),
    softwareApplicationJsonLd({ origin: url, name: t("brand.name"), offers, playStoreUrl }),
  ];
}

// ---- Solution (keyword landing) pages: docs/seo/keyword-map.md -------------------------------

const solutionNamespace = (slug: SolutionSlug) => `marketing.solutions.pages.${slug}`;

export async function solutionMetadata(slug: SolutionSlug): Promise<Metadata> {
  const [t, brand] = await Promise.all([
    getTranslations(`${solutionNamespace(slug)}.meta`),
    getTranslations("marketing.brand"),
  ]);
  return pageMetadata({
    title: t("title"),
    description: t("description"),
    path: solutionPath(slug),
    siteName: brand("name"),
  });
}

export async function solutionsHubMetadata(): Promise<Metadata> {
  const [t, brand] = await Promise.all([
    getTranslations("marketing.solutions.hub.meta"),
    getTranslations("marketing.brand"),
  ]);
  return pageMetadata({
    title: t("title"),
    description: t("description"),
    path: SOLUTIONS_HUB_PATH,
    siteName: brand("name"),
  });
}

/** Home → Solutions (→ page). The trail follows the real click path through the hub. */
export async function solutionsBreadcrumb(slug?: SolutionSlug): Promise<Record<string, unknown>> {
  const [t, hub] = await Promise.all([getTranslations("marketing"), getTranslations("marketing.solutions.hub")]);
  const { url } = getSiteConfig();
  const trail = [
    { name: t("brand.name"), path: PATHS.home },
    { name: hub("breadcrumb"), path: SOLUTIONS_HUB_PATH },
  ];
  if (slug) {
    const page = await getTranslations(solutionNamespace(slug));
    trail.push({ name: page("breadcrumb"), path: solutionPath(slug) });
  }
  return breadcrumbJsonLd(url, trail);
}
