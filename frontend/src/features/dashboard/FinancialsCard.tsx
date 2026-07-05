import { Landmark } from "lucide-react";
import { MoneyRow, MoneyStat } from "@/components/shared/MoneyStat";
import type { FinancialsSummary } from "./types";

export function FinancialsCard({ data }: { data: FinancialsSummary }) {
  return (
    <section className="relative overflow-hidden rounded-2xl bg-surface-inverse p-5 shadow-md">
      <Landmark
        className="absolute -top-2 right-3 size-16 text-ink-inverse/10"
        aria-hidden
      />
      <h2 className="relative mb-4 text-base font-bold text-ink-inverse">
        Financials
      </h2>

      <MoneyStat
        label="Monthly Revenue"
        amount={data.monthlyRevenue}
        delta={data.revenueDelta}
        inverse
        className="relative mb-5"
      />

      <div className="relative space-y-2 border-t border-white/10 pt-4">
        <MoneyRow
          label="Outstanding Dues"
          amount={data.outstandingDues}
          attention
        />
        <MoneyRow
          label="Security Deposits"
          amount={data.securityDeposits}
          emphasis
        />
      </div>
    </section>
  );
}
