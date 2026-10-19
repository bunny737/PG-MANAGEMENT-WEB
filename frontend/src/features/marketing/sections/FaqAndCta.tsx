import { ChevronDown } from "lucide-react";
import { getTranslations } from "next-intl/server";
import { ButtonLink } from "@/components/marketing/ButtonLink";
import { JsonLd } from "@/components/marketing/JsonLd";
import { Section, SectionHeading } from "@/components/marketing/Section";
import { PrimaryCtaButton } from "../PrimaryCtaButton";

export async function FaqSection() {
  const t = await getTranslations("marketing.faq");
  const items = t.raw("items") as { q: string; a: string }[];

  return (
    <Section id="faq">
      <JsonLd
        data={{
          "@context": "https://schema.org",
          "@type": "FAQPage",
          mainEntity: items.map((item) => ({
            "@type": "Question",
            name: item.q,
            acceptedAnswer: { "@type": "Answer", text: item.a },
          })),
        }}
      />
      <SectionHeading title={t("title")} />
      <div className="mx-auto mt-10 max-w-3xl divide-y divide-border rounded-2xl border border-border bg-surface-card">
        {items.map((item) => (
          <details key={item.q} className="group px-5 py-4">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-4 text-left text-base font-semibold [&::-webkit-details-marker]:hidden">
              {item.q}
              <ChevronDown
                className="size-5 shrink-0 text-ink-muted transition-transform group-open:rotate-180"
                aria-hidden="true"
              />
            </summary>
            <p className="mt-3 text-sm text-ink-muted">{item.a}</p>
          </details>
        ))}
      </div>
    </Section>
  );
}

export async function FinalCta() {
  const [t, tCta] = await Promise.all([getTranslations("marketing.finalCta"), getTranslations("marketing.cta")]);
  return (
    <Section tone="dark">
      <div className="mx-auto max-w-2xl text-center">
        <h2 className="text-3xl font-extrabold sm:text-4xl">{t("title")}</h2>
        <p className="mt-4 text-lg text-ink-inverse-muted">{t("body")}</p>
        <div className="mt-8 flex flex-wrap justify-center gap-3">
          <PrimaryCtaButton variant="inverse" />
          <ButtonLink href="/contact" variant="ghost" size="lg" className="text-ink-inverse hover:bg-white/10 hover:text-ink-inverse">
            {tCta("contactUs")}
          </ButtonLink>
        </div>
      </div>
    </Section>
  );
}
