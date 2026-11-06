import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { GoogleAnalytics } from "@/components/marketing/GoogleAnalytics";
import { MarketingFooter } from "@/components/marketing/MarketingFooter";
import { MarketingHeader } from "@/components/marketing/MarketingHeader";
import { getSiteConfig } from "@/lib/site-config";

// The root layout defaults every route to noindex (the signed-in app must never
// be indexed); the public marketing pages opt back in here.
// Per-page openGraph/twitter live in features/marketing/seoCore.ts (pageMetadata): Next merges
// metadata shallowly, so setting them here would be replaced by every page anyway.
export function generateMetadata(): Metadata {
  const { url } = getSiteConfig();
  return {
    metadataBase: new URL(url),
    robots: { index: true, follow: true },
  };
}

export default async function MarketingLayout({ children }: { children: React.ReactNode }) {
  const t = await getTranslations("marketing.nav");
  return (
    <>
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-surface-card focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:shadow-lg"
      >
        {t("skipToContent")}
      </a>
      <MarketingHeader />
      <main id="main" className="flex-1">
        {children}
      </main>
      <MarketingFooter />
      <GoogleAnalytics />
    </>
  );
}
