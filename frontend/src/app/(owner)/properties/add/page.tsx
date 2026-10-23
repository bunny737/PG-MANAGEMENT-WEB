"use client";

import { RequirePermission } from "@/components/shared/RequirePermission";
import { PropertyForm } from "@/features/properties/PropertyForm";

export default function AddPropertyPage() {
  return (
    <RequirePermission permission="manage_properties">
      <main className="mx-auto w-full max-w-5xl px-4 py-8 md:px-8">
        <PropertyForm />
      </main>
    </RequirePermission>
  );
}
