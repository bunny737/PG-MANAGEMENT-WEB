"use client";

import { Suspense } from "react";
import { RequirePermission } from "@/components/shared/RequirePermission";
import { ExpensesPage } from "@/features/expenses/ExpensesPage";

export default function ExpensesRoute() {
  return (
    <RequirePermission permission="view_expenses">
      <main className="mx-auto w-full max-w-6xl px-4 py-8 md:px-8">
        <Suspense>
          <ExpensesPage />
        </Suspense>
      </main>
    </RequirePermission>
  );
}
