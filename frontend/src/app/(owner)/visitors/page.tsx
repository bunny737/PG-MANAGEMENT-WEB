"use client";

import { RequirePermission } from "@/components/shared/RequirePermission";
import { VisitorsLog } from "@/features/visitors/VisitorsLog";

export default function VisitorsPage() {
  return (
    <RequirePermission permission="manage_visitors">
      <main className="mx-auto w-full max-w-5xl px-4 py-8 md:px-8">
        <VisitorsLog />
      </main>
    </RequirePermission>
  );
}
