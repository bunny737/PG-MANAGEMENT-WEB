"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { RequirePermission } from "@/components/shared/RequirePermission";
import { AdmissionWizard } from "@/features/admissions/AdmissionWizard";

function AdmissionsContent() {
  // A bed chosen on the Vacancies screen arrives as ?property=<id>&bed=<id>.
  const searchParams = useSearchParams();
  const property = searchParams.get("property");
  const bed = searchParams.get("bed");

  return <AdmissionWizard preselect={property && bed ? { propertyId: property, bedId: bed } : undefined} />;
}

export default function AdmissionsPage() {
  return (
    <RequirePermission permission="manage_admissions">
      <main className="mx-auto w-full max-w-5xl px-4 py-8 md:px-8">
        <Suspense>
          <AdmissionsContent />
        </Suspense>
      </main>
    </RequirePermission>
  );
}
