import { Clock, Globe, Mail, MapPin, MessageCircle, Phone } from "lucide-react";
import { getTranslations } from "next-intl/server";
import { ButtonLink } from "@/components/marketing/ButtonLink";
import { Section, SectionHeading } from "@/components/marketing/Section";
import { getSiteConfig } from "@/lib/site-config";
import { formatPhone, getSupportContacts, hasContactInfo, telHref } from "../data/support";
import { PrimaryCtaButton } from "../PrimaryCtaButton";

function Row({
  Icon,
  label,
  children,
}: {
  Icon: typeof Mail;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-start gap-4 rounded-2xl border border-border bg-surface-card p-5">
      <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-accent-soft text-accent">
        <Icon className="size-5" aria-hidden="true" />
      </span>
      <div className="min-w-0">
        <dt className="text-xs font-bold uppercase tracking-wider text-ink-faint">{label}</dt>
        <dd className="mt-1 break-words text-base font-semibold text-ink">{children}</dd>
      </div>
    </div>
  );
}

/** Contact details come from the Super-Admin-managed support config
 * (GET /api/v1/support/), so they can change without a deploy. */
export async function ContactChannels() {
  const [t, support] = await Promise.all([getTranslations("marketing.contact"), getSupportContacts()]);
  const { company } = getSiteConfig();

  return (
    <Section>
      <SectionHeading pageTitle title={t("title")} subtitle={t("subtitle")} />

      {hasContactInfo(support, company.address) ? (
        <dl className="mx-auto mt-10 grid max-w-3xl gap-4 sm:grid-cols-2">
          {support?.email && (
            <Row Icon={Mail} label={t("email")}>
              <a href={`mailto:${support.email}`} className="text-accent hover:underline">
                {support.email}
              </a>
            </Row>
          )}
          {support?.phone && (
            <Row Icon={Phone} label={t("phone")}>
              <a href={telHref(support.phone)} className="text-accent hover:underline">
                {formatPhone(support.phone)}
              </a>
            </Row>
          )}
          {support?.whatsapp && support.whatsapp_url && (
            <Row Icon={MessageCircle} label={t("whatsapp")}>
              <a
                href={support.whatsapp_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-accent hover:underline"
              >
                {formatPhone(support.whatsapp)}
              </a>
            </Row>
          )}
          {support?.website && (
            <Row Icon={Globe} label={t("website")}>
              <a
                href={support.website}
                target="_blank"
                rel="noopener noreferrer"
                className="text-accent hover:underline"
              >
                {support.website}
              </a>
            </Row>
          )}
          {support?.hours && (
            <Row Icon={Clock} label={t("hours")}>
              {support.hours}
            </Row>
          )}
          {company.address && (
            <Row Icon={MapPin} label={t("address")}>
              {company.name}
              <br />
              {company.address}
            </Row>
          )}
        </dl>
      ) : (
        <div
          role="status"
          className="mx-auto mt-10 max-w-xl rounded-2xl border border-border bg-surface-card p-6 text-center"
        >
          <h2 className="text-lg font-bold">{t("unavailable.title")}</h2>
          <p className="mt-2 text-sm text-ink-muted">{t("unavailable.body")}</p>
        </div>
      )}

      <div className="mx-auto mt-10 max-w-3xl rounded-3xl bg-surface-inverse p-7 text-ink-inverse">
        <h2 className="text-xl font-bold">{t("earlyAccess.title")}</h2>
        <p className="mt-2 text-sm text-ink-inverse-muted">{t("earlyAccess.body")}</p>
        <div className="mt-5 flex flex-wrap gap-3">
          <PrimaryCtaButton variant="inverse" />
          {support?.whatsapp_url && (
            <ButtonLink
              href={support.whatsapp_url}
              external
              variant="ghost"
              size="lg"
              className="text-ink-inverse hover:bg-white/10 hover:text-ink-inverse"
            >
              {t("chatOnWhatsapp")}
            </ButtonLink>
          )}
        </div>
      </div>
    </Section>
  );
}
