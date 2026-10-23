"use client";

import { use } from "react";
import { RequirePermission } from "@/components/shared/RequirePermission";
import { PropertyForm } from "@/features/properties/PropertyForm";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function EditPropertyPage({ params }: PageProps) {
  const { id } = use(params);
  return (
    <RequirePermission permission="manage_properties">
      <main className="mx-auto w-full max-w-5xl px-4 py-8 md:px-8">
        <PropertyForm propertyId={id} />
      </main>
    </RequirePermission>
  );
}
