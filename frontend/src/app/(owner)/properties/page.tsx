import { Suspense } from "react";
import { RequirePermission } from "@/components/shared/RequirePermission";
import { PropertyList } from "@/features/properties/PropertyList";

export default function PropertiesPortfolioPage() {
  return (
    <RequirePermission permission="view_property_features">
      <main className="mx-auto w-full max-w-5xl p-0 md:px-8 md:py-8">
        <Suspense>
          <PropertyList />
        </Suspense>
      </main>
    </RequirePermission>
  );
}
