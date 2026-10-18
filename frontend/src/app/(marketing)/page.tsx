import { JsonLd } from "@/components/marketing/JsonLd";
import { AppShowcase } from "@/features/marketing/sections/AppShowcase";
import { FaqSection, FinalCta } from "@/features/marketing/sections/FaqAndCta";
import { FeatureHighlights, HowItWorks } from "@/features/marketing/sections/FeatureSections";
import { Hero } from "@/features/marketing/sections/Hero";
import { PricingSection } from "@/features/marketing/sections/PricingSection";
import { RolesSection, TrustStrip } from "@/features/marketing/sections/TrustAndRoles";
import { marketingMetadata, organizationJsonLd } from "@/features/marketing/seo";

export const generateMetadata = () => marketingMetadata("home");

export default async function HomePage() {
  const structuredData = await organizationJsonLd();
  return (
    <>
      {structuredData.map((entry) => (
        <JsonLd key={String(entry["@type"])} data={entry} />
      ))}
      <Hero />
      <TrustStrip />
      <FeatureHighlights />
      <RolesSection />
      <HowItWorks />
      <AppShowcase />
      <PricingSection variant="teaser" />
      <FaqSection />
      <FinalCta />
    </>
  );
}
