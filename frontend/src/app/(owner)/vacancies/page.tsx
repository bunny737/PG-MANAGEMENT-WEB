import { Suspense } from "react";
import { RequirePermission } from "@/components/shared/RequirePermission";
import { VacanciesScreen } from "@/features/vacancies/VacanciesScreen";
import { LAYOUT_ENTRY_PERMISSIONS } from "@/lib/layoutAccess";

// Reads each property's bed layout, so it needs the same entry permissions as the property overview.
export default function VacanciesPage() {
  return (
    <RequirePermission anyOf={[...LAYOUT_ENTRY_PERMISSIONS]}>
      <main className="mx-auto w-full p-0">
        <Suspense>
          <VacanciesScreen />
        </Suspense>
      </main>
    </RequirePermission>
  );
}
