"use client";

import { RequirePermission } from "@/components/shared/RequirePermission";
import { ComplaintsDashboard } from "@/features/complaints/ComplaintsDashboard";

export default function ComplaintsPage() {
  return (
    <RequirePermission permission="manage_complaints">
      <main className="mx-auto w-full max-w-5xl px-4 py-8 md:px-8">
        <ComplaintsDashboard />
      </main>
    </RequirePermission>
  );
}
