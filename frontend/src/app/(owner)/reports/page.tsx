"use client";

import { Suspense } from "react";
import { RequirePermission } from "@/components/shared/RequirePermission";
import { ReportsPage } from "@/features/reports/ReportsPage";

export default function ReportsRoute() {
  return (
    <RequirePermission anyOf={["view_reports", "view_dashboard"]}>
      <main className="mx-auto w-full max-w-6xl px-4 py-8 md:px-8">
        <Suspense>
          <ReportsPage />
        </Suspense>
      </main>
    </RequirePermission>
  );
}
