"use client";

import { use } from "react";
import { RequirePermission } from "@/components/shared/RequirePermission";
import { AddFloorForm } from "@/features/properties/AddFloorForm";

interface PageProps {
  params: Promise<{ id: string; buildingId: string }>;
}

export default function BuildingAddFloorPage({ params }: PageProps) {
  const { id, buildingId } = use(params);
  return (
    <RequirePermission permission="manage_rooms_beds">
      <main className="mx-auto w-full max-w-5xl px-4 py-8 md:px-8">
        <AddFloorForm propertyId={id} buildingId={buildingId} />
      </main>
    </RequirePermission>
  );
}
