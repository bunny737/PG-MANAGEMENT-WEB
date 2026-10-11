"use client";

import { RequirePermission } from "@/components/shared/RequirePermission";
import { AdmissionWizard } from "@/features/admissions/AdmissionWizard";

export default function AdmissionsPage() {
  return (
    <RequirePermission permission="manage_admissions">
      <main className="mx-auto w-full max-w-5xl px-4 py-8 md:px-8">
        <AdmissionWizard />
      </main>
    </RequirePermission>
  );
}
