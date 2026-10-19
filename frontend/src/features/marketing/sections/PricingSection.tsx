import { Check } from "lucide-react";
import { getTranslations } from "next-intl/server";
import { ButtonLink } from "@/components/marketing/ButtonLink";
import { Section, SectionHeading } from "@/components/marketing/Section";
import { StatusPill } from "@/components/shared/StatusPill";
import { compareMoney, formatMoney } from "@/lib/money";
import { cn } from "@/lib/utils";
import { getPlanCatalog, type PublicPlan } from "../data/plans";
import { PrimaryCtaButton } from "../PrimaryCtaButton";

const BILLING_NOTES = ["beds", "billingTiming", "changePlan", "razorpay", "suspended"] as const;

type Translate = (key: string, values?: Record<string, string | number>) => string;

function PerBedTiers({ plan, t }: { plan: PublicPlan; t: Translate }) {
  return (
    <ul className="mt-4 space-y-2 text-sm">
      {plan.bed_tiers.map((tier, index) => {
        const heading =
          index === 0 && tier.up_to_beds !== null
            ? t("perBed.firstBeds", { beds: tier.up_to_beds })
            : tier.up_to_beds !== null
              ? t("perBed.nextBeds", { beds: tier.up_to_beds })
              : t("perBed.restBeds");
        const free = compareMoney(tier.rate_per_bed, "0.00") === 0;
        return (
          <li key={`${tier.up_to_beds ?? "rest"}-${index}`} className="flex items-start gap-2">
            <Check className="mt-0.5 size-4 shrink-0 text-status-good" aria-hidden="true" />
            <span>
              <span className="font-semibold text-ink">{heading}:</span>{" "}
              <span className="text-ink-muted">
                {free ? t("perBed.free") : t("perBed.rate", { rate: formatMoney(tier.rate_per_bed) })}
              </span>
            </span>
          </li>
        );
      })}
    </ul>
  );
}

/** Plans come only from GET /public/plans/ (invariant 10). If the API is down and
 * nothing was ever fetched we say so — we never show baked-in prices. */
export async function PricingSection({ variant = "full" }: { variant?: "teaser" | "full" }) {
  const [t, tCta, catalog] = await Promise.all([
    getTranslations("marketing.pricing"),
    getTranslations("marketing.cta"),
    getPlanCatalog(),
  ]);
  const heading = (
    <SectionHeading pageTitle={variant === "full"} title={t("title")} subtitle={t("subtitle")} />
  );

  if (catalog.status === "unavailable") {
    return (
      <Section id="pricing" tone={variant === "full" ? "default" : "subtle"}>
        {heading}
        <div
          role="status"
          className="mx-auto mt-10 max-w-xl rounded-2xl border border-border bg-surface-card p-6 text-center"
        >
          <h2 className="text-lg font-bold">{t("unavailable.title")}</h2>
          <p className="mt-2 text-sm text-ink-muted">{t("unavailable.body")}</p>
          <div className="mt-5 flex justify-center">
            <ButtonLink href="/contact" variant="secondary">
              {tCta("contactUs")}
            </ButtonLink>
          </div>
        </div>
      </Section>
    );
  }

  const { plans, trial_days: trialDays } = catalog.data;

  return (
    <Section id="pricing" tone={variant === "full" ? "default" : "subtle"}>
      {heading}
      <p className="mt-4 text-center text-sm font-semibold text-accent">{t("trialDays", { days: trialDays })}</p>

      <ul className="mt-10 grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        {plans.map((plan) => (
          <li
            key={plan.id}
            className={cn(
              "flex flex-col rounded-3xl border bg-surface-card p-7 shadow-sm",
              plan.is_trial_plan ? "border-accent ring-2 ring-accent-soft" : "border-border"
            )}
          >
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-xl font-extrabold">{plan.name}</h3>
              {plan.is_trial_plan && <StatusPill label={t("trialBadge")} tone="accent" />}
            </div>

            {plan.pricing_type === "flat_monthly" && plan.price_per_month !== null ? (
              <p className="mt-5">
                <span className="font-display text-4xl font-extrabold tabular-nums">
                  {formatMoney(plan.price_per_month)}
                </span>{" "}
                <span className="text-sm text-ink-muted">{t("perMonth")}</span>
              </p>
            ) : (
              <>
                <p className="mt-5 font-display text-2xl font-extrabold">{t("perBed.title")}</p>
                <PerBedTiers plan={plan} t={t} />
              </>
            )}

            {plan.pricing_type === "flat_monthly" && (
              <p className="mt-4 flex items-start gap-2 text-sm">
                <Check className="mt-0.5 size-4 shrink-0 text-status-good" aria-hidden="true" />
                <span className="font-semibold text-ink">
                  {plan.max_beds === null ? t("unlimitedBeds") : t("upToBeds", { beds: plan.max_beds })}
                </span>
              </p>
            )}

            <div className="mt-auto pt-7">
              <PrimaryCtaButton className="w-full" />
            </div>
          </li>
        ))}
      </ul>

      {variant === "full" ? (
        <div className="mx-auto mt-12 max-w-3xl rounded-2xl border border-border bg-surface-card p-6">
          <h2 className="text-base font-bold">{t("notesTitle")}</h2>
          <ul className="mt-3 space-y-2 text-sm text-ink-muted">
            {BILLING_NOTES.map((note) => (
              <li key={note} className="flex items-start gap-2">
                <Check className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden="true" />
                {t(`notes.${note}`)}
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <div className="mt-8 text-center">
          <ButtonLink href="/pricing" variant="secondary">
            {tCta("seePricing")}
          </ButtonLink>
        </div>
      )}
    </Section>
  );
}
