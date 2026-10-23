"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { ArrowLeft, Download, Share2 } from "lucide-react";
import { downloadReceiptPdf, getReceipt } from "@/lib/api";
import { MoneyText } from "@/components/shared/MoneyText";
import { SectionError, SectionSkeleton } from "@/components/shared/SectionState";
import { StatusPill, getStatusTone } from "@/components/shared/StatusPill";
import { queryKeys } from "@/lib/queryKeys";
import { triggerDownload } from "@/lib/download";

export function ReceiptView({ id }: { id: string }) {
  const t = useTranslations("billing.receipt");
  const tStatus = useTranslations("status");

  const { data: receipt, isLoading, isError, refetch } = useQuery({
    queryKey: queryKeys.payments.receipt(id),
    queryFn: () => getReceipt(id),
  });

  async function handleDownload() {
    triggerDownload(await downloadReceiptPdf(id));
  }

  async function handleShare() {
    const { blob, filename } = await downloadReceiptPdf(id);
    const file = new File([blob], filename, { type: "application/pdf" });
    if (navigator.share && navigator.canShare?.({ files: [file] })) {
      await navigator.share({ files: [file], title: t("title") });
    } else {
      triggerDownload({ blob, filename });
    }
  }

  if (isLoading) return <SectionSkeleton className="h-96" />;
  if (isError || !receipt) return <SectionError onRetry={() => refetch()} message={t("errLoadFailed")} />;

  const rows: [string, React.ReactNode][] = [
    [t("resident"), receipt.resident],
    [t("property"), receipt.property_name],
    [t("roomBed"), receipt.room_number ? `${receipt.room_number} / ${receipt.bed_number}` : "—"],
    [t("period"), `${receipt.period_start} – ${receipt.period_end}`],
    [t("mode"), tStatus(receipt.payment_mode)],
    [t("date"), receipt.payment_date],
    [t("reference"), receipt.reference || "—"],
    [t("recordedBy"), receipt.recorded_by_name ?? "—"],
    [t("invoiceStatus"), <StatusPill key="s" label={tStatus(receipt.invoice_status)} tone={getStatusTone(receipt.invoice_status)} />],
    [t("invoiceTotal"), <MoneyText key="t" value={receipt.invoice_total} />],
    [t("invoicePaid"), <MoneyText key="p" value={receipt.invoice_paid} />],
    [t("invoiceBalance"), <MoneyText key="b" value={receipt.invoice_balance_due} />],
  ];

  return (
    <div className="mx-auto max-w-lg space-y-6">
      <Link href="/billing" className="inline-flex items-center gap-1.5 text-sm font-medium text-ink-muted hover:text-ink">
        <ArrowLeft className="size-4" />
        {t("back")}
      </Link>

      <div className="rounded-2xl border border-border bg-surface-card p-6">
        <div className="mb-4 flex items-center justify-between border-b border-border pb-4">
          <div>
            <h1 className="text-lg font-bold text-ink">{t("title")}</h1>
            <p className="text-sm text-ink-muted">{receipt.receipt_number ?? t("receiptNo")}</p>
          </div>
          <MoneyText value={receipt.amount} className="text-2xl font-bold text-ink" />
        </div>
        <dl className="space-y-2 text-sm">
          {rows.map(([label, value]) => (
            <div key={typeof label === "string" ? label : String(value)} className="flex items-center justify-between">
              <dt className="text-ink-muted">{label}</dt>
              <dd className="font-medium text-ink">{value}</dd>
            </div>
          ))}
        </dl>
        <div className="mt-6 flex gap-2">
          <button
            type="button"
            onClick={handleDownload}
            className="flex flex-1 items-center justify-center gap-1.5 rounded-xl border border-border bg-surface-page py-2 text-sm font-semibold text-ink transition-colors hover:bg-surface-subtle cursor-pointer"
          >
            <Download className="size-4" />
            {t("downloadPdf")}
          </button>
          <button
            type="button"
            onClick={handleShare}
            className="flex flex-1 items-center justify-center gap-1.5 rounded-xl bg-accent py-2 text-sm font-semibold text-ink-inverse transition-colors hover:bg-accent-hover cursor-pointer"
          >
            <Share2 className="size-4" />
            {t("share")}
          </button>
        </div>
      </div>
    </div>
  );
}
