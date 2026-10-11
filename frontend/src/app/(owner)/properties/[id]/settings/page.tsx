"use client";

import { use } from "react";
import { RequirePermission } from "@/components/shared/RequirePermission";
import { PropertySettingsForm } from "@/features/properties/PropertySettingsForm";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function PropertySettingsPage({ params }: PageProps) {
  const { id } = use(params);
  return (
    <RequirePermission permission="manage_property_settings">
      <main className="mx-auto w-full max-w-5xl px-4 py-8 md:px-8">
        <PropertySettingsForm propertyId={id} />
      </main>
    </RequirePermission>
  );
}
