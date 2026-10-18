import { getTranslations } from "next-intl/server";
import { ProgressBar } from "@/components/shared/ProgressBar";
import { StatusPill } from "@/components/shared/StatusPill";
import { formatMoney } from "@/lib/money";
import { PhoneFrame } from "./PhoneFrame";

// Sample figures for the illustrative screens (Decimal strings, never floats).
const SAMPLE = {
  rent: "6500.00",
  discount: "-500.00",
  electricity: "320.00",
  total: "6320.00",
  collected: "412000.00",
  pending: "38500.00",
  occupancyPercent: 82,
};

async function frameProps(screen: "residentHome" | "invoice" | "complaint" | "ownerDashboard") {
  const t = await getTranslations("marketing.app");
  return {
    role: t(`screens.${screen}.role`),
    title: t(`screens.${screen}.title`),
    availability: t(`screens.${screen}.availability`),
    previewLabel: t("previewLabel"),
  };
}

export async function ResidentHomePreview() {
  const [t, frame] = await Promise.all([getTranslations("marketing.app.sample"), frameProps("residentHome")]);
  return (
    <PhoneFrame {...frame}>
      <p className="text-sm font-bold text-ink">{t("greeting")}</p>
      <div className="rounded-2xl bg-surface-inverse p-3.5 text-ink-inverse">
        <p className="text-[11px] uppercase tracking-wider text-ink-inverse-muted">{t("rentDue")}</p>
        <p className="mt-1 font-display text-2xl font-extrabold">{formatMoney(SAMPLE.total)}</p>
        <p className="mt-0.5 text-[11px] text-ink-inverse-muted">{t("dueOn")}</p>
      </div>
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-ink-muted">{t("recent")}</p>
      </div>
      <div className="flex items-center justify-between rounded-xl border border-border bg-surface-card px-3 py-2.5">
        <div>
          <p className="text-xs font-semibold text-ink">{t("october")}</p>
          <p className="text-[11px] text-ink-muted">{formatMoney("6320.00")}</p>
        </div>
        <StatusPill label={t("status.paid")} tone="good" dot />
      </div>
      <div className="flex items-center justify-between rounded-xl border border-border bg-surface-card px-3 py-2.5">
        <p className="text-xs font-semibold text-ink">{t("rentDue")}</p>
        <StatusPill label={t("status.due")} tone="warn" dot />
      </div>
    </PhoneFrame>
  );
}

export async function InvoicePreview() {
  const [t, frame] = await Promise.all([getTranslations("marketing.app.sample"), frameProps("invoice")]);
  const lines = [
    { label: t("lineRent"), amount: SAMPLE.rent },
    { label: t("lineDiscount"), amount: SAMPLE.discount },
    { label: t("lineElectricity"), amount: SAMPLE.electricity },
  ];
  return (
    <PhoneFrame {...frame}>
      <div className="flex items-center justify-between">
        <p className="text-sm font-bold text-ink">{t("invoiceTitle")}</p>
        <StatusPill label={t("status.due")} tone="warn" dot />
      </div>
      <div className="divide-y divide-border rounded-xl border border-border bg-surface-card">
        {lines.map((line) => (
          <div key={line.label} className="flex items-center justify-between px-3 py-2.5 text-xs">
            <span className="text-ink-muted">{line.label}</span>
            <span className="font-semibold tabular-nums text-ink">{formatMoney(line.amount)}</span>
          </div>
        ))}
        <div className="flex items-center justify-between px-3 py-2.5 text-xs">
          <span className="font-bold text-ink">{t("lineTotal")}</span>
          <span className="font-display text-sm font-extrabold tabular-nums text-ink">
            {formatMoney(SAMPLE.total)}
          </span>
        </div>
      </div>
    </PhoneFrame>
  );
}

export async function ComplaintPreview() {
  const [t, frame] = await Promise.all([getTranslations("marketing.app.sample"), frameProps("complaint")]);
  const steps = [
    { label: t("stepOpen"), done: true },
    { label: t("stepAssigned"), done: true },
    { label: t("stepProgress"), done: false },
  ];
  return (
    <PhoneFrame {...frame}>
      <div>
        <p className="text-sm font-bold text-ink">{t("complaintTitle")}</p>
        <p className="text-[11px] text-ink-muted">{t("complaintRoom")}</p>
      </div>
      <StatusPill label={t("status.assigned")} tone="warn" dot />
      <ol className="space-y-3 rounded-xl border border-border bg-surface-card p-3">
        {steps.map((step) => (
          <li key={step.label} className="flex items-center gap-2.5 text-xs">
            <span
              className={`size-2.5 rounded-full ${step.done ? "bg-status-good" : "border-2 border-border-strong"}`}
            />
            <span className={step.done ? "font-semibold text-ink" : "text-ink-muted"}>{step.label}</span>
          </li>
        ))}
      </ol>
    </PhoneFrame>
  );
}

export async function OwnerDashboardPreview() {
  const [t, frame] = await Promise.all([getTranslations("marketing.app.sample"), frameProps("ownerDashboard")]);
  return (
    <PhoneFrame {...frame}>
      <div className="rounded-2xl border border-border bg-surface-card p-3">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-ink-faint">{t("occupancy")}</p>
        <p className="mt-1 font-display text-2xl font-extrabold text-ink">{SAMPLE.occupancyPercent}%</p>
        <div className="mt-2">
          <ProgressBar percent={SAMPLE.occupancyPercent} label={t("occupiedBeds")} />
        </div>
        <p className="mt-1.5 text-[11px] text-ink-muted">{t("occupiedBeds")}</p>
      </div>
      {/* Compact tiles: the shared StatTile's figure size overflows a phone-width screen. */}
      {[
        { label: t("collected"), value: SAMPLE.collected },
        { label: t("pending"), value: SAMPLE.pending },
      ].map((tile) => (
        <div key={tile.label} className="rounded-xl border border-border bg-surface-card px-3 py-2.5">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-ink-faint">{tile.label}</p>
          <p className="mt-0.5 font-display text-lg font-extrabold tabular-nums text-ink">
            {formatMoney(tile.value)}
          </p>
        </div>
      ))}
    </PhoneFrame>
  );
}
