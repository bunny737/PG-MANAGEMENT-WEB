import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { getTranslations } from "next-intl/server";
import { ButtonLink } from "@/components/marketing/ButtonLink";
import { Container, Section, SectionHeading } from "@/components/marketing/Section";
import { PrimaryCtaButton } from "../PrimaryCtaButton";
import { SOLUTION_PAGES, SOLUTIONS_HUB_PATH, solutionPath, type SolutionSlug } from "../content/landing";

const pageNamespace = (slug: SolutionSlug) => `marketing.solutions.pages.${slug}`;

export async function SolutionHero({ slug }: { slug: SolutionSlug }) {
  const [t, tCta] = await Promise.all([getTranslations(pageNamespace(slug)), getTranslations("marketing.cta")]);
  return (
    <div className="bg-surface-card">
      <Container className="py-14 sm:py-20">
        <div className="max-w-3xl">
          <p className="inline-block rounded-full bg-accent-soft px-3 py-1 text-xs font-bold uppercase tracking-wider text-accent">
            {t("eyebrow")}
          </p>
          <h1 className="mt-5 text-4xl font-extrabold leading-[1.1] sm:text-5xl">{t("title")}</h1>
          <p className="mt-5 max-w-2xl text-lg text-ink-muted">{t("intro")}</p>
          <div className="mt-8 flex flex-wrap gap-3">
            <PrimaryCtaButton />
            <ButtonLink href="/pricing" variant="secondary" size="lg">
              {tCta("seePricing")}
            </ButtonLink>
          </div>
        </div>
      </Container>
    </div>
  );
}

export async function SolutionBody({ slug }: { slug: SolutionSlug }) {
  const t = await getTranslations(pageNamespace(slug));
  const sections = t.raw("sections") as { heading: string; body: string }[];
  return (
    <Section tone="subtle">
      <div className="mx-auto max-w-3xl space-y-10">
        {sections.map((section) => (
          <div key={section.heading}>
            <h2 className="text-2xl font-bold">{section.heading}</h2>
            <p className="mt-3 text-base text-ink-muted">{section.body}</p>
          </div>
        ))}
      </div>
    </Section>
  );
}

async function SolutionCards({ exclude }: { exclude?: SolutionSlug }) {
  const [t, tLinks] = await Promise.all([
    getTranslations("marketing.solutions.pages"),
    getTranslations("marketing.solutionLinks"),
  ]);
  return (
    <ul className="mt-10 grid gap-6 md:grid-cols-3">
      {SOLUTION_PAGES.filter((page) => page.slug !== exclude).map((page) => (
        <li key={page.slug} className="flex flex-col rounded-2xl border border-border bg-surface-card p-6 shadow-xs">
          <h3 className="text-lg font-bold">{t(`${page.slug}.nav`)}</h3>
          <p className="mt-2 flex-1 text-sm text-ink-muted">{t(`${page.slug}.summary`)}</p>
          <Link
            href={solutionPath(page.slug)}
            className="mt-4 inline-flex items-center gap-1.5 text-sm font-semibold text-accent hover:underline"
          >
            {tLinks("viewPage")}
            <ArrowRight className="size-4" aria-hidden="true" />
          </Link>
        </li>
      ))}
    </ul>
  );
}

/** Internal links to the solution pages, for the home page, /features and between the pages. */
export async function SolutionLinks({ exclude }: { exclude?: SolutionSlug }) {
  const t = await getTranslations("marketing.solutionLinks");
  return (
    <Section id="solutions">
      <SectionHeading title={t("title")} subtitle={t("subtitle")} />
      <SolutionCards exclude={exclude} />
      <div className="mt-10 text-center">
        <ButtonLink href={SOLUTIONS_HUB_PATH} variant="secondary" size="lg">
          {t("hubCta")}
        </ButtonLink>
      </div>
    </Section>
  );
}

/** The /solutions hub: its h1 and a card for every solution page. */
export async function SolutionsHub() {
  const t = await getTranslations("marketing.solutions.hub");
  return (
    <Section>
      <SectionHeading pageTitle eyebrow={t("eyebrow")} title={t("title")} subtitle={t("subtitle")} />
      <SolutionCards />
    </Section>
  );
}
