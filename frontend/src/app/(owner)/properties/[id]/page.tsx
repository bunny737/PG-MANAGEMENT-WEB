"use client";

import { Suspense, use } from "react";
import { RequirePermission } from "@/components/shared/RequirePermission";
import { PropertyOverview } from "@/features/properties/PropertyOverview";

interface PageProps {
  params: Promise<{ id: string }>;
}

// D2: the bed-grid overview, replacing the old redirect to /buildings. The
// building/floor/room/bed management screens are still reachable from here
// (each room links to its management route).
export default function PropertyDetailPage({ params }: PageProps) {
  const { id } = use(params);

  return (
    <RequirePermission
      anyOf={["view_property_features", "manage_rooms_beds", "manage_admissions", "manage_allocations"]}
    >
      <main className="mx-auto w-full max-w-6xl px-4 py-8 md:px-8">
        <Suspense>
          <PropertyOverview propertyId={id} />
        </Suspense>
      </main>
    </RequirePermission>
  );
}
