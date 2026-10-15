"use client";

import { RequirePermission } from "@/components/shared/RequirePermission";
import { FinancialsDashboard } from "@/features/financials/FinancialsDashboard";

export default function FinancialsPage() {
  return (
    <RequirePermission permission="view_finance">
      <main className="mx-auto w-full max-w-5xl px-4 py-8 md:px-8">
        <FinancialsDashboard />
      </main>
    </RequirePermission>
  );
}
