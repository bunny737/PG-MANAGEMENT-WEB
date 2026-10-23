"use client";

import { use } from "react";
import { RequirePermission } from "@/components/shared/RequirePermission";
import { AddRoomForm } from "@/features/properties/AddRoomForm";

interface PageProps {
  params: Promise<{ id: string; floorId: string }>;
}

export default function PropertyAddRoomPage({ params }: PageProps) {
  const { id, floorId } = use(params);
  return (
    <RequirePermission permission="manage_rooms_beds">
      <main className="mx-auto w-full max-w-5xl px-4 py-8 md:px-8">
        <AddRoomForm propertyId={id} floorId={floorId} />
      </main>
    </RequirePermission>
  );
}
