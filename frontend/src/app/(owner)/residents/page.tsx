import { Suspense } from "react";
import { RequirePermission } from "@/components/shared/RequirePermission";
import { ResidentsDirectory } from "@/features/residents/ResidentsDirectory";

export default function ResidentsPage() {
  return (
    <RequirePermission permission="view_resident_profile">
      <main className="mx-auto w-full max-w-5xl p-0 md:px-8 md:py-8">
        <Suspense>
          <ResidentsDirectory />
        </Suspense>
      </main>
    </RequirePermission>
  );
}
