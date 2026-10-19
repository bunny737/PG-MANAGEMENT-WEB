import { FinalCta } from "@/features/marketing/sections/FaqAndCta";
import { FeatureMatrix } from "@/features/marketing/sections/FeatureSections";
import { marketingMetadata } from "@/features/marketing/seo";

export const generateMetadata = () => marketingMetadata("features");

export default function FeaturesPage() {
  return (
    <>
      <FeatureMatrix />
      <FinalCta />
    </>
  );
}
