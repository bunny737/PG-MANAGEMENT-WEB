import { JsonLd } from "@/components/marketing/JsonLd";
import { FaqSection } from "@/features/marketing/sections/FaqAndCta";
import { PricingSection } from "@/features/marketing/sections/PricingSection";
import { marketingMetadata, organizationJsonLd } from "@/features/marketing/seo";

export const generateMetadata = () => marketingMetadata("pricing");

export default async function PricingPage() {
  const structuredData = await organizationJsonLd();
  return (
    <>
      {structuredData
        .filter((entry) => entry["@type"] === "SoftwareApplication")
        .map((entry) => (
          <JsonLd key="software" data={entry} />
        ))}
      <PricingSection variant="full" />
      <FaqSection />
    </>
  );
}
