import { getTranslations } from "next-intl/server";
import { ButtonLink } from "@/components/marketing/ButtonLink";
import { Section, SectionHeading } from "@/components/marketing/Section";
import { AvailabilityBadge } from "../AvailabilityBadge";
import {
  FEATURES,
  FEATURE_GROUPS,
  HIGHLIGHT_KEYS,
  SURFACES,
  featuresInGroup,
  type Availability,
} from "../content/features";
import { FEATURE_ICONS } from "../featureIcons";

const STATES: Availability[] = ["available", "preview", "comingSoon", "notPlanned"];

export async function FeatureHighlights() {
  const [t, tCta] = await Promise.all([
    getTranslations("marketing.features"),
    getTranslations("marketing.cta"),
  ]);
  const highlights = HIGHLIGHT_KEYS.map((key) => FEATURES.find((feature) => feature.key === key)).filter(
    (feature) => feature !== undefined
  );

  return (
    <Section id="features">
      <SectionHeading title={t("highlightsTitle")} subtitle={t("subtitle")} />
      <ul className="mt-10 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
        {highlights.map((feature) => {
          const Icon = FEATURE_ICONS[feature.key];
          return (
            <li key={feature.key} className="rounded-2xl border border-border bg-surface-card p-6 shadow-xs">
              <span className="flex size-11 items-center justify-center rounded-xl bg-accent-soft text-accent">
                {Icon && <Icon className="size-5" aria-hidden="true" />}
              </span>
              <h3 className="mt-4 text-lg font-bold">{t(`items.${feature.key}.title`)}</h3>
              <p className="mt-2 text-sm text-ink-muted">{t(`items.${feature.key}.description`)}</p>
              <div className="mt-4">
                <AvailabilityBadge
                  state={feature.availability.ownerWeb}
                  label={`${t("surfaces.ownerWeb")}: ${t(`states.${feature.availability.ownerWeb}`)}`}
                />
              </div>
            </li>
          );
        })}
      </ul>
      <div className="mt-10 text-center">
        <ButtonLink href="/features" variant="secondary" size="lg">
          {tCta("seeFeatures")}
        </ButtonLink>
      </div>
    </Section>
  );
}

/** The full catalogue, with per-surface availability for every feature. */
export async function FeatureMatrix() {
  const t = await getTranslations("marketing.features");

  return (
    <>
      <Section>
        <SectionHeading pageTitle title={t("title")} subtitle={t("subtitle")} />
        <div className="mx-auto mt-10 max-w-3xl rounded-2xl border border-border bg-surface-card p-5">
          <h2 className="text-sm font-bold uppercase tracking-wider text-ink-muted">{t("legendTitle")}</h2>
          <dl className="mt-4 grid gap-3 sm:grid-cols-2">
            {STATES.map((state) => (
              <div key={state} className="flex items-start gap-3">
                <dt className="shrink-0">
                  <AvailabilityBadge state={state} label={t(`states.${state}`)} />
                </dt>
                <dd className="text-sm text-ink-muted">{t(`legend.${state}`)}</dd>
              </div>
            ))}
          </dl>
        </div>
      </Section>

      {FEATURE_GROUPS.map((group, index) => (
        <Section key={group} tone={index % 2 === 0 ? "subtle" : "default"} className="py-12 sm:py-14">
          <h2 className="text-2xl font-extrabold">{t(`groups.${group}`)}</h2>
          <ul className="mt-8 grid gap-6 md:grid-cols-2 lg:grid-cols-3">
            {featuresInGroup(group).map((feature) => {
              const Icon = FEATURE_ICONS[feature.key];
              return (
                <li
                  key={feature.key}
                  className="flex flex-col rounded-2xl border border-border bg-surface-card p-6 shadow-xs"
                >
                  <span className="flex size-11 items-center justify-center rounded-xl bg-accent-soft text-accent">
                    {Icon && <Icon className="size-5" aria-hidden="true" />}
                  </span>
                  <h3 className="mt-4 text-lg font-bold">{t(`items.${feature.key}.title`)}</h3>
                  <p className="mt-2 flex-1 text-sm text-ink-muted">{t(`items.${feature.key}.description`)}</p>
                  <dl className="mt-5 space-y-2 border-t border-border pt-4">
                    {SURFACES.map((surface) => (
                      <div key={surface} className="flex items-center justify-between gap-3">
                        <dt className="text-xs font-medium text-ink-muted">{t(`surfaces.${surface}`)}</dt>
                        <dd>
                          <AvailabilityBadge
                            state={feature.availability[surface]}
                            label={t(`states.${feature.availability[surface]}`)}
                          />
                        </dd>
                      </div>
                    ))}
                  </dl>
                </li>
              );
            })}
          </ul>
        </Section>
      ))}
    </>
  );
}

export async function HowItWorks() {
  const t = await getTranslations("marketing.how");
  const steps = t.raw("steps") as { title: string; body: string }[];
  return (
    <Section tone="subtle">
      <SectionHeading title={t("title")} />
      <ol className="mt-10 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
        {steps.map((step, index) => (
          <li key={step.title} className="rounded-2xl border border-border bg-surface-page p-5">
            <span className="flex size-9 items-center justify-center rounded-full bg-accent font-display text-base font-extrabold text-ink-inverse">
              {index + 1}
            </span>
            <h3 className="mt-4 text-base font-bold">{step.title}</h3>
            <p className="mt-2 text-sm text-ink-muted">{step.body}</p>
          </li>
        ))}
      </ol>
    </Section>
  );
}
