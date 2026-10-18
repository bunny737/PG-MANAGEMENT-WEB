"use client";

import { Suspense } from "react";
import { RequirePermission } from "@/components/shared/RequirePermission";
import { BillingTabs } from "@/features/billing/BillingTabs";

export default function BillingPage() {
  return (
    <RequirePermission permission="view_finance">
      <main className="mx-auto w-full max-w-6xl px-4 py-8 md:px-8">
        <Suspense>
          <BillingTabs />
        </Suspense>
      </main>
    </RequirePermission>
  );
}
