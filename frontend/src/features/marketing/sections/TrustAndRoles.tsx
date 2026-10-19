import { BedDouble, Languages, ScrollText, ShieldCheck } from "lucide-react";
import { getTranslations } from "next-intl/server";
import { Section, SectionHeading } from "@/components/marketing/Section";
import { StatusPill } from "@/components/shared/StatusPill";

const TRUST = [
  { key: "isolation", Icon: ShieldCheck },
  { key: "rent", Icon: BedDouble },
  { key: "audit", Icon: ScrollText },
  { key: "languages", Icon: Languages },
] as const;

export async function TrustStrip() {
  const t = await getTranslations("marketing.trust");
  return (
    <Section tone="subtle">
      <SectionHeading title={t("title")} />
      <ul className="mt-10 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
        {TRUST.map(({ key, Icon }) => (
          <li key={key} className="rounded-2xl border border-border bg-surface-page p-5">
            <span className="flex size-10 items-center justify-center rounded-xl bg-accent-soft text-accent">
              <Icon className="size-5" aria-hidden="true" />
            </span>
            <h3 className="mt-4 text-base font-bold">{t(`items.${key}.title`)}</h3>
            <p className="mt-2 text-sm text-ink-muted">{t(`items.${key}.body`)}</p>
          </li>
        ))}
      </ul>
    </Section>
  );
}

const ROLES = ["owner", "manager", "receptionist", "resident"] as const;

export async function RolesSection() {
  const [t, tFeatures] = await Promise.all([
    getTranslations("marketing.roles"),
    getTranslations("marketing.features.states"),
  ]);
  return (
    <Section>
      <SectionHeading title={t("title")} />
      <ul className="mt-10 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
        {ROLES.map((role) => (
          <li key={role} className="rounded-2xl border border-border bg-surface-card p-5 shadow-xs">
            <h3 className="text-lg font-bold">{t(`${role}.title`)}</h3>
            <p className="mt-2 text-sm text-ink-muted">{t(`${role}.body`)}</p>
            {role === "resident" && (
              <div className="mt-4 space-y-1.5">
                <StatusPill label={tFeatures("comingSoon")} tone="neutral" dot />
                <p className="text-xs text-ink-muted">{t("resident.note")}</p>
              </div>
            )}
          </li>
        ))}
      </ul>
    </Section>
  );
}
