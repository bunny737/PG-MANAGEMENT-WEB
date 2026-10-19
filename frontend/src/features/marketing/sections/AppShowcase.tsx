import { Smartphone } from "lucide-react";
import { getTranslations } from "next-intl/server";
import { ButtonLink } from "@/components/marketing/ButtonLink";
import { Section, SectionHeading } from "@/components/marketing/Section";
import { getSiteConfig } from "@/lib/site-config";
import { getSupportContacts } from "../data/support";
import {
  ComplaintPreview,
  InvoicePreview,
  OwnerDashboardPreview,
  ResidentHomePreview,
} from "../previews/screens";

/** Android section: concept previews, the permanent QR code and the download state.
 * The QR encodes https://pglive.in/app, never the Play URL, so it can be printed
 * today and keeps working after launch. */
export async function AppShowcase({ isPage = false }: { isPage?: boolean }) {
  const [t, support] = await Promise.all([getTranslations("marketing.app"), getSupportContacts()]);
  const { appStatus, playStoreUrl } = getSiteConfig();
  const live = appStatus === "live" && playStoreUrl !== null;

  const notify = support?.whatsapp_url
    ? `${support.whatsapp_url}?text=${encodeURIComponent(t("notifyMessage"))}`
    : support?.email
      ? `mailto:${support.email}?subject=${encodeURIComponent(t("notifySubject"))}&body=${encodeURIComponent(t("notifyMessage"))}`
      : "/contact";
  const notifyExternal = notify.startsWith("http") || notify.startsWith("mailto:");

  return (
    <Section id="app" tone={isPage ? "default" : "subtle"}>
      <SectionHeading
        pageTitle={isPage}
        eyebrow={t("eyebrow")}
        title={t("title")}
        subtitle={live ? t("subtitleLive") : t("subtitle")}
      />

      <div className="mt-8 flex justify-center">
        <span
          className={`inline-flex items-center gap-2 rounded-full px-4 py-1.5 text-sm font-semibold ${
            live ? "bg-status-good-soft text-status-good" : "bg-status-warn-soft text-status-warn"
          }`}
        >
          <Smartphone className="size-4" aria-hidden="true" />
          {live ? t("badgeLive") : t("badgeComingSoon")}
        </span>
      </div>

      <div className="mt-10 grid grid-cols-1 gap-8 sm:grid-cols-2 lg:grid-cols-4">
        <ResidentHomePreview />
        <InvoicePreview />
        <ComplaintPreview />
        <OwnerDashboardPreview />
      </div>
      <p className="mt-6 text-center text-sm text-ink-muted">{t("previewNote")}</p>

      <div className="mx-auto mt-12 grid max-w-3xl items-center gap-8 rounded-3xl border border-border bg-surface-card p-6 shadow-md sm:grid-cols-[auto_1fr] sm:p-8">
        {/* eslint-disable-next-line @next/next/no-img-element -- static SVG, no optimisation needed */}
        <img
          src="/qr-app.svg"
          alt={t("qrAlt")}
          width={176}
          height={176}
          className="mx-auto size-44 rounded-xl border border-border bg-white p-2"
        />
        <div className="text-center sm:text-left">
          <h3 className="text-xl font-bold text-ink">{t("scanTitle")}</h3>
          <p className="mt-2 text-sm text-ink-muted">{t("scanBody")}</p>
          <div className="mt-5 flex flex-wrap justify-center gap-3 sm:justify-start">
            {live && playStoreUrl ? (
              // Swap for Google's official badge artwork when the listing is live
              // (Play brand guidelines); the text button keeps the link usable until then.
              <ButtonLink href={playStoreUrl} external size="lg">
                {t("getOnPlay")}
              </ButtonLink>
            ) : (
              <ButtonLink href={notify} external={notifyExternal} size="lg">
                {t("notifyCta")}
              </ButtonLink>
            )}
          </div>
          {!live && (
            <p className="mt-3 text-xs text-ink-muted">
              <span className="font-semibold">{t("notifyTitle")}</span> {t("notifyBody")}
            </p>
          )}
        </div>
      </div>

      <div className="mx-auto mt-8 max-w-3xl">
        <h3 className="text-sm font-bold uppercase tracking-wider text-ink-muted">{t("requirementsTitle")}</h3>
        <ul className="mt-3 list-disc space-y-1.5 pl-5 text-sm text-ink-muted">
          {(t.raw("requirements") as string[]).map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </div>
    </Section>
  );
}
