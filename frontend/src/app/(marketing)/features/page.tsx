import { FinalCta } from "@/features/marketing/sections/FaqAndCta";
import { FeatureMatrix } from "@/features/marketing/sections/FeatureSections";
import { marketingMetadata } from "@/features/marketing/seo";
import { PageBreadcrumb } from "@/components/marketing/PageBreadcrumb";

export const generateMetadata = () => marketingMetadata("features");

export default function FeaturesPage() {
  return (
    <>
      <PageBreadcrumb page="features" />
      <FeatureMatrix />
      <FinalCta />
    </>
  );
}
