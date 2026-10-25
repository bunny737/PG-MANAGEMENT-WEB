import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { JsonLd } from "@/components/marketing/JsonLd";
import { FaqSection, FinalCta } from "@/features/marketing/sections/FaqAndCta";
import { FeatureHighlights } from "@/features/marketing/sections/FeatureSections";
import { SolutionBody, SolutionHero, SolutionLinks } from "@/features/marketing/sections/LandingSections";
import { PricingSection } from "@/features/marketing/sections/PricingSection";
import { SOLUTION_PAGES, findSolution } from "@/features/marketing/content/landing";
import { solutionMetadata, solutionsBreadcrumb } from "@/features/marketing/seo";

// Only the slugs in content/landing.ts exist; anything else is a real 404.
export const dynamicParams = false;

export function generateStaticParams() {
  return SOLUTION_PAGES.map((page) => ({ slug: page.slug }));
}

type Props = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const page = findSolution((await params).slug);
  return page ? solutionMetadata(page.slug) : {};
}

export default async function SolutionPage({ params }: Props) {
  const page = findSolution((await params).slug);
  if (!page) notFound();

  return (
    <>
      <JsonLd data={await solutionsBreadcrumb(page.slug)} />
      <SolutionHero slug={page.slug} />
      <SolutionBody slug={page.slug} />
      <FeatureHighlights keys={page.featureKeys} />
      <PricingSection variant="teaser" />
      <FaqSection namespace={`marketing.solutions.pages.${page.slug}.faq`} />
      <SolutionLinks exclude={page.slug} />
      <FinalCta />
    </>
  );
}
