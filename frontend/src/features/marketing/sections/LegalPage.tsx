import { getTranslations } from "next-intl/server";
import { Section, SectionHeading } from "@/components/marketing/Section";
import { ButtonLink } from "@/components/marketing/ButtonLink";
import { getSiteConfig } from "@/lib/site-config";
import { formatPhone, getSupportContacts, telHref } from "../data/support";

async function renderLegal(kind: "privacy" | "terms" | "refund") {
  const t = await getTranslations("marketing.legal");
  const { company } = getSiteConfig();
  const sections = t.raw(`${kind}.sections`) as { heading: string; body: string }[];

  return (
    <Section>
      <SectionHeading pageTitle alignLeft title={t(`${kind}.title`)} />
      <p className="mt-4 text-sm text-ink-muted">{t(`${kind}.updated`)}</p>
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
export const RefundPolicyDocument = () => renderLegal("refund");

/** The public "Delete your PGLive account" page (Google Play's Delete account URL). Unlike the
 * other legal documents it ends with the way to act: sign in to start the request, and how to reach
 * support for someone who cannot sign in. Contact details come from the Super-Admin-managed support
 * config, so they can change without a deploy. */
export async function DeleteAccountDocument() {
  const [t, support] = await Promise.all([getTranslations("marketing"), getSupportContacts()]);
  const { company } = getSiteConfig();
  const sections = t.raw("legal.deleteAccount.sections") as { heading: string; body: string }[];

  return (
    <Section>
      <SectionHeading pageTitle alignLeft title={t("legal.deleteAccount.title")} />
      <p className="mt-4 text-sm text-ink-muted">{t("legal.deleteAccount.updated")}</p>
      <p className="mt-6 max-w-3xl text-base text-ink-muted">{t("legal.deleteAccount.intro", { company: company.name })}</p>
      <div className="mt-8">
        <ButtonLink href="/login" size="lg">
          {t("legal.deleteAccount.signIn")}
        </ButtonLink>
      </div>
      <div className="mt-10 max-w-3xl space-y-8">
        {sections.map((section) => (
          <div key={section.heading}>
            <h2 className="text-xl font-bold">{section.heading}</h2>
            <p className="mt-2 text-base text-ink-muted">{section.body}</p>
          </div>
        ))}
        <div>
          <h2 className="text-xl font-bold">{t("legal.deleteAccount.contactHeading")}</h2>
          <p className="mt-2 text-base text-ink-muted">{t("legal.deleteAccount.contactBody")}</p>
          <ul className="mt-3 space-y-1 text-base">
            {support?.email && (
              <li>
                <a href={`mailto:${support.email}`} className="text-accent hover:underline">
                  {support.email}
                </a>
              </li>
            )}
            {support?.phone && (
              <li>
                <a href={telHref(support.phone)} className="text-accent hover:underline">
                  {formatPhone(support.phone)}
                </a>
              </li>
            )}
          </ul>
          <div className="mt-4">
            <ButtonLink href="/contact" variant="secondary">
              {t("footer.company")}
            </ButtonLink>
          </div>
        </div>
      </div>
    </Section>
  );
}
