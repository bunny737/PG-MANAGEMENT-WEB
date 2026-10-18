import { getTranslations } from "next-intl/server";
import { ButtonLink } from "@/components/marketing/ButtonLink";
import { Container } from "@/components/marketing/Section";
import { ProgressBar } from "@/components/shared/ProgressBar";
import { StatTile } from "@/components/shared/StatTile";
import { formatMoney } from "@/lib/money";
import { getSiteConfig } from "@/lib/site-config";
import { PrimaryCtaButton } from "../PrimaryCtaButton";

export async function Hero() {
  const [t, tCta] = await Promise.all([getTranslations("marketing.hero"), getTranslations("marketing.cta")]);
  const { signupEnabled } = getSiteConfig();

  return (
    <div className="relative overflow-hidden bg-surface-card">
      <div
        aria-hidden="true"
        className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,var(--color-accent-soft),transparent_55%)]"
      />
      <Container className="relative grid items-center gap-12 py-14 sm:py-20 lg:grid-cols-2">
        <div>
          <p className="inline-block rounded-full bg-accent-soft px-3 py-1 text-xs font-bold uppercase tracking-wider text-accent">
            {t("eyebrow")}
          </p>
          <h1 className="mt-5 text-4xl font-extrabold leading-[1.1] sm:text-5xl">{t("title")}</h1>
          <p className="mt-5 max-w-xl text-lg text-ink-muted">{t("subtitle")}</p>
          <div className="mt-8 flex flex-wrap gap-3">
            <PrimaryCtaButton />
            <ButtonLink href="/pricing" variant="secondary" size="lg">
              {tCta("seePricing")}
            </ButtonLink>
          </div>
          <p className="mt-4 text-sm text-ink-muted">{signupEnabled ? t("noteTrial") : t("noteEarlyAccess")}</p>
        </div>

        {/* Decorative illustration of the owner dashboard; the figures are samples. */}
        <div aria-hidden="true" className="mx-auto w-full max-w-md">
          <div className="rounded-3xl border border-border bg-surface-page p-5 shadow-lg">
            <div className="rounded-2xl border border-border bg-surface-card p-4">
              <p className="text-xs font-semibold uppercase tracking-wider text-ink-faint">{t("cardOccupancy")}</p>
              <p className="mt-1 font-display text-4xl font-extrabold">82%</p>
              <div className="mt-3">
                <ProgressBar percent={82} />
              </div>
            </div>
            <div className="mt-3 grid grid-cols-2 gap-3">
              <StatTile label={t("cardCollected")} value={formatMoney("412000.00")} dot="accent" />
              <StatTile label={t("cardDue")} value={formatMoney("38500.00")} dot="neutral" />
            </div>
            <p className="mt-3 text-center text-[11px] text-ink-faint">{t("illustrative")}</p>
          </div>
        </div>
      </Container>
    </div>
  );
}
