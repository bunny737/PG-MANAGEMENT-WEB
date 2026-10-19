import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { ButtonLink } from "@/components/marketing/ButtonLink";
import { MarketingFooter } from "@/components/marketing/MarketingFooter";
import { MarketingHeader } from "@/components/marketing/MarketingHeader";
import { Section } from "@/components/marketing/Section";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("marketing.meta.notFound");
  return { title: t("title"), robots: { index: false, follow: false } };
}

// App-wide 404 (an unmatched URL has no route group), so it carries its own chrome.
export default async function NotFound() {
  const t = await getTranslations("marketing.notFound");
  return (
    <>
      <MarketingHeader />
      <main className="flex-1">
        <Section>
          <div className="mx-auto max-w-lg text-center">
            <h1 className="text-3xl font-extrabold sm:text-4xl">{t("title")}</h1>
            <p className="mt-4 text-lg text-ink-muted">{t("body")}</p>
            <div className="mt-8 flex justify-center">
              <ButtonLink href="/" size="lg">
                {t("home")}
              </ButtonLink>
            </div>
          </div>
        </Section>
      </main>
      <MarketingFooter />
    </>
  );
}
