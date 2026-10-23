"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Download } from "lucide-react";
import {
  type ExportFiletype,
  exportCashFlowStatement,
  exportExpenses,
  exportOccupancy,
  exportOutstandingDues,
  exportPayments,
  exportResidents,
} from "@/lib/api";
import { PermissionGate } from "@/components/shared/PermissionGate";
import { triggerDownload } from "@/lib/download";

const FILETYPES: ExportFiletype[] = ["csv", "xlsx", "pdf"];

interface ExportRowProps {
  label: string;
  onDownload: (filetype: ExportFiletype) => Promise<{ blob: Blob; filename: string }>;
}

function ExportRow({ label, onDownload }: ExportRowProps) {
  const t = useTranslations("reports.exports");
  const [filetype, setFiletype] = useState<ExportFiletype>("xlsx");
  const [downloading, setDownloading] = useState(false);

  async function handleDownload() {
    setDownloading(true);
    try {
      triggerDownload(await onDownload(filetype));
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="flex items-center justify-between gap-3 rounded-xl border border-border bg-surface-card px-4 py-3">
      <span className="text-sm font-semibold text-ink">{label}</span>
      <div className="flex items-center gap-2">
        <select
          value={filetype}
          onChange={(event) => setFiletype(event.target.value as ExportFiletype)}
          className="rounded-lg border border-border bg-surface-card px-2 py-1 text-xs text-ink outline-none"
        >
          {FILETYPES.map((ft) => (
            <option key={ft} value={ft}>
              {ft.toUpperCase()}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={handleDownload}
          disabled={downloading}
          className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-xs font-semibold text-ink-inverse transition-colors hover:bg-accent-hover disabled:opacity-60 cursor-pointer"
        >
          <Download className="size-3.5" />
          {t("download")}
        </button>
      </div>
    </div>
  );
}

export function ExportsTab({ month, propertyId }: { month: string; propertyId: string | null }) {
  const t = useTranslations("reports.exports");
  const property = propertyId ?? undefined;

  return (
    <div className="space-y-3">
      <PermissionGate permission="view_resident_profile">
        <ExportRow label={t("residents")} onDownload={(ft) => exportResidents(ft, property)} />
      </PermissionGate>
      <PermissionGate permission="view_finance">
        <ExportRow label={t("payments")} onDownload={(ft) => exportPayments(ft, month, property)} />
      </PermissionGate>
      <PermissionGate permission="view_finance">
        <ExportRow label={t("outstandingDues")} onDownload={(ft) => exportOutstandingDues(ft, month, property)} />
      </PermissionGate>
      <PermissionGate permission="view_reports">
        <ExportRow label={t("occupancy")} onDownload={(ft) => exportOccupancy(ft, property)} />
      </PermissionGate>
      <PermissionGate permission="view_expenses">
        <ExportRow label={t("expenses")} onDownload={(ft) => exportExpenses(ft, month, property)} />
      </PermissionGate>
      <PermissionGate allOf={["view_finance", "view_expenses"]}>
        <ExportRow label={t("pnl")} onDownload={(ft) => exportCashFlowStatement(ft, month, property)} />
      </PermissionGate>
    </div>
  );
}
