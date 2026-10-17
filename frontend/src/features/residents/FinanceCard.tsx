"use client";

import { useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { MessageCircle } from "lucide-react";
import { MoneyText } from "@/components/shared/MoneyText";
import { PermissionGate } from "@/components/shared/PermissionGate";
import { StatusPill, getStatusTone } from "@/components/shared/StatusPill";
import { formatMoney } from "@/lib/money";
import { normalizePhoneE164 } from "@/lib/phone";
import type { Resident } from "@/lib/api";
import { GenerateInvoiceDialog } from "@/features/billing/GenerateInvoiceDialog";

/**
 * D6 resident finance block, replacing the old (always-empty, since
 * `resident.invoices` never matched the real API shape) Financials tab.
 * Covers every roadmap card state: no invoice (+ prior outstanding, +
 * draft-not-issued), one invoice, several invoices, partial payment, and
 * prior arrears. `resident.finance` is null (with "finance" in
 * `resident.redacted`) without view_finance — the caller gates the whole
 * tab on that already, so this component assumes `finance` is present.
 */
export function FinanceCard({ resident }: { resident: Resident }) {
  const t = useTranslations("residents.profile.financials");
  const tStatus = useTranslations("status");
  const [showGenerate, setShowGenerate] = useState(false);
  const finance = resident.finance;

  if (!finance) return null;

  const { current_period: period } = finance;
  const fullName = `${resident.first_name} ${resident.last_name}`.trim();
  const outstandingHref = `/billing?resident=${resident.id}&status=outstanding`;
  const e164 = normalizePhoneE164(resident.phone);
  const reminderHref = e164
    ? `https://wa.me/${e164.replace("+", "")}?text=${encodeURIComponent(
        t("reminderMessage", { name: fullName, amount: formatMoney(finance.outstanding_total) })
      )}`
    : undefined;

  return (
    <div className="space-y-4 animate-fade-in">
      <div className="rounded-2xl border border-border bg-surface-card p-5 shadow-sm">
        <h3 className="mb-3 text-xs font-bold uppercase tracking-wider text-ink-faint">
          {t("currentPeriod", { period: period.period })}
        </h3>

        {period.status === "no_invoice" ? (
          <div className="space-y-2">
            <p className="text-sm font-semibold text-ink">{t("noInvoiceTitle", { period: period.period })}</p>
            {Number(finance.prior_outstanding) > 0 && (
              <p className="text-sm text-status-critical">
                <MoneyText value={finance.prior_outstanding} /> {t("priorOutstandingNotice")}
              </p>
            )}
            {period.has_draft && <p className="text-xs text-ink-muted">{t("draftNotice")}</p>}
            <PermissionGate permission="manage_invoices">
              <button
                type="button"
                onClick={() => setShowGenerate(true)}
                className="mt-2 rounded-xl bg-accent px-3 py-2 text-xs font-semibold text-ink-inverse transition-colors hover:bg-accent-hover cursor-pointer"
              >
                {t("generateInvoice")}
              </button>
            </PermissionGate>
          </div>
        ) : (
          <div className="space-y-3">
            {period.invoices.length > 1 && (
              <p className="text-xs text-ink-muted">{t("invoicesCount", { count: period.invoices.length })}</p>
            )}
            <div className="grid grid-cols-3 gap-2 text-center">
              <div>
                <p className="text-[10px] uppercase text-ink-faint">{t("total")}</p>
                <MoneyText value={period.total} className="font-bold text-ink" />
              </div>
              <div>
                <p className="text-[10px] uppercase text-ink-faint">{t("paid")}</p>
                <MoneyText value={period.paid} className="font-bold text-status-good" />
              </div>
              <div>
                <p className="text-[10px] uppercase text-ink-faint">{t("due")}</p>
                <MoneyText value={period.balance} className="font-bold text-status-critical" attention={Number(period.balance) > 0} />
              </div>
            </div>
            {Number(period.total) > 0 && (
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-border">
                <div
                  className="h-full bg-status-good"
                  style={{ width: `${Math.min(100, (Number(period.paid) / Number(period.total)) * 100)}%` }}
                />
              </div>
            )}
            <div className="flex items-center justify-between">
              <StatusPill label={tStatus(period.status)} tone={getStatusTone(period.status)} />
              {period.invoices.length === 1 && (
                <Link
                  href={`/billing/invoices/${period.invoices[0].id}`}
                  className="text-xs font-semibold text-accent hover:text-accent-hover"
                >
                  {t("recordPayment")} ›
                </Link>
              )}
              {period.invoices.length > 1 && (
                <Link href={outstandingHref} className="text-xs font-semibold text-accent hover:text-accent-hover">
                  {t("recordPayment")} ›
                </Link>
              )}
            </div>
          </div>
        )}
      </div>

      {Number(finance.outstanding_total) > 0 && (
        <div className="rounded-2xl border border-border bg-surface-card p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-[10px] uppercase text-ink-faint">{t("outstandingTotal")}</p>
              <MoneyText value={finance.outstanding_total} className="text-lg font-bold text-ink" />
            </div>
            {Number(finance.overdue_total) > 0 && (
              <div className="text-right">
                <p className="text-[10px] uppercase text-ink-faint">{t("overdueTotal")}</p>
                <MoneyText value={finance.overdue_total} className="font-bold text-status-critical" attention />
              </div>
            )}
          </div>
          {Number(finance.prior_outstanding) > 0 && (
            <p className="mt-2 text-xs text-ink-muted">
              {t("priorOutstanding")}: <MoneyText value={finance.prior_outstanding} />
            </p>
          )}
          <div className="mt-3 flex items-center gap-3">
            <Link href={outstandingHref} className="text-xs font-semibold text-accent hover:text-accent-hover">
              {t("viewOutstanding")} ›
            </Link>
            <PermissionGate permission="view_finance">
              {reminderHref ? (
                <a
                  href={reminderHref}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-xs font-semibold text-status-good hover:underline"
                >
                  <MessageCircle className="size-3.5" />
                  {t("sendReminder")}
                </a>
              ) : null}
            </PermissionGate>
          </div>
        </div>
      )}

      {finance.last_payment_date && (
        <p className="text-xs text-ink-muted">
          {t("lastPayment")}: {finance.last_payment_date}
        </p>
      )}

      {showGenerate && (
        <GenerateInvoiceDialog
          onClose={() => setShowGenerate(false)}
          onCreated={() => setShowGenerate(false)}
          propertyId={resident.property}
          residentId={resident.id}
          residentName={fullName}
        />
      )}
    </div>
  );
}
