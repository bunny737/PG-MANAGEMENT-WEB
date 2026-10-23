"use client";

import { RequirePermission } from "@/components/shared/RequirePermission";
import { StaffDirectory } from "@/features/staff/StaffDirectory";

export default function StaffPage() {
  return (
    <RequirePermission permission="manage_staff_accounts">
      <main className="mx-auto w-full max-w-6xl px-4 py-8 md:px-8">
        <StaffDirectory />
      </main>
    </RequirePermission>
  );
}
