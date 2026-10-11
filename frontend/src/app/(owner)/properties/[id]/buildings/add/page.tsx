"use client";

import { use } from "react";
import { RequirePermission } from "@/components/shared/RequirePermission";
import { AddBuildingForm } from "@/features/properties/AddBuildingForm";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function PropertyAddBuildingPage({ params }: PageProps) {
  const { id } = use(params);
  return (
    <RequirePermission permission="manage_rooms_beds">
      <main className="mx-auto w-full max-w-5xl px-4 py-8 md:px-8">
        <AddBuildingForm propertyId={id} />
      </main>
    </RequirePermission>
  );
}
