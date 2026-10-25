import { JsonLd } from "@/components/marketing/JsonLd";
import { FinalCta } from "@/features/marketing/sections/FaqAndCta";
import { SolutionsHub } from "@/features/marketing/sections/LandingSections";
import { solutionsBreadcrumb, solutionsHubMetadata } from "@/features/marketing/seo";

export const generateMetadata = () => solutionsHubMetadata();

export default async function SolutionsPage() {
  return (
    <>
      <JsonLd data={await solutionsBreadcrumb()} />
      <SolutionsHub />
      <FinalCta />
    </>
  );
}
