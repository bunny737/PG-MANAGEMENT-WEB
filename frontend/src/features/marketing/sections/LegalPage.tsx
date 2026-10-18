import { getTranslations } from "next-intl/server";
import { Section, SectionHeading } from "@/components/marketing/Section";
import { getSiteConfig } from "@/lib/site-config";

async function renderLegal(kind: "privacy" | "terms") {
  const t = await getTranslations("marketing.legal");
  const { company } = getSiteConfig();
  const sections = t.raw(`${kind}.sections`) as { heading: string; body: string }[];

  return (
    <Section>
      <SectionHeading pageTitle alignLeft title={t(`${kind}.title`)} />
      <p
        role="note"
        className="mt-6 max-w-3xl rounded-xl border border-status-warn/30 bg-status-warn-soft px-4 py-3 text-sm font-medium text-status-warn"
      >
        {t("draftNotice")}
      </p>
      <p className="mt-6 max-w-3xl text-base text-ink-muted">{t(`${kind}.intro`, { company: company.name })}</p>
      <div className="mt-8 max-w-3xl space-y-8">
        {sections.map((section) => (
          <div key={section.heading}>
            <h2 className="text-xl font-bold">{section.heading}</h2>
            <p className="mt-2 text-base text-ink-muted">{section.body}</p>
          </div>
        ))}
      </div>
    </Section>
  );
}

export const PrivacyDocument = () => renderLegal("privacy");
export const TermsDocument = () => renderLegal("terms");
