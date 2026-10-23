import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { getPlanCatalog } from "./data/plans";
import { getSupportContacts } from "./data/support";
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

const PATHS: Record<MarketingPage, string> = {
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

/** Per-page title/description/canonical. The locale only changes the text, never
 * the URL, so English is the canonical, indexed version (frontend-plan.md). */
export async function marketingMetadata(page: MarketingPage): Promise<Metadata> {
  const t = await getTranslations(`marketing.meta.${page}`);
  const path = PATHS[page];
  return {
    title: t("title"),
    description: t("description"),
    alternates: { canonical: path },
    openGraph: { title: t("title"), description: t("description"), url: path },
  };
}

/** Organization + SoftwareApplication structured data. Offers are built from the
 * live plan catalogue, so they can never disagree with the pricing page. */
export async function organizationJsonLd(): Promise<Record<string, unknown>[]> {
  const [t, support, catalog] = await Promise.all([
    getTranslations("marketing"),
    getSupportContacts(),
    getPlanCatalog(),
  ]);
  const { url, company } = getSiteConfig();

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
      ...(contactPoint.length ? { contactPoint } : {}),
    },
    {
      "@context": "https://schema.org",
      "@type": "SoftwareApplication",
      name: t("brand.name"),
      applicationCategory: "BusinessApplication",
      operatingSystem: "Web",
      url,
      ...(offers.length ? { offers } : {}),
    },
  ];
}
