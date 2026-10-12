"use client";

import { use } from "react";
import { RequirePermission } from "@/components/shared/RequirePermission";
import { StaffAccess } from "@/features/staff/StaffAccess";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function StaffAccessPage({ params }: PageProps) {
  const { id } = use(params);
  return (
    <RequirePermission permission="manage_staff_accounts">
      <main className="mx-auto w-full max-w-6xl px-4 py-8 md:px-8">
        <StaffAccess staffId={id} />
      </main>
    </RequirePermission>
  );
}
