"use client";

import { Landmark } from "lucide-react";
import { useTranslations } from "next-intl";
import { MoneyRow, MoneyStat } from "@/components/shared/MoneyStat";
import type { FinancialsSummary } from "./types";

export function FinancialsCard({ data }: { data: FinancialsSummary }) {
  const t = useTranslations("dashboard.financials");

  return (
    <section className="relative flex h-full flex-col justify-between overflow-hidden rounded-2xl bg-linear-to-br from-slate-900 via-slate-800 to-slate-950 p-5.5 shadow-md ring-1 ring-white/10 transition-all hover:ring-white/20">
      <Landmark
        className="absolute -top-4 -right-3 size-28 text-white/[0.04] pointer-events-none"
        aria-hidden
        strokeWidth={1.2}
      />
      <div>
        <h2 className="relative mb-4 flex items-center gap-2.5 font-display text-base font-bold text-white">
          <span className="flex size-8.5 items-center justify-center rounded-xl bg-white/10 text-white ring-1 ring-white/15 backdrop-blur-xs">
            <Landmark className="size-4.5" aria-hidden />
          </span>
          {t("title")}
        </h2>

        <MoneyStat
          label={t("monthlyRevenue")}
          amount={data.monthlyRevenue}
          delta={data.revenueDelta}
          inverse
          className="relative mb-4"
        />
      </div>

      <div className="relative space-y-2 border-t border-white/10 pt-3.5">
        <MoneyRow
          label={t("outstandingDues")}
          amount={data.outstandingDues}
          attention
        />
        <MoneyRow
          label={t("securityDeposits")}
          amount={data.securityDeposits}
          emphasis
        />
      </div>
    </section>
  );
}
