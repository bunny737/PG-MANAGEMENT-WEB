import { RequirePermission } from "@/components/shared/RequirePermission";
import { PropertyList } from "@/features/properties/PropertyList";

export default function PropertiesPortfolioPage() {
  return (
    <RequirePermission permission="view_property_features">
      <main className="mx-auto w-full max-w-5xl px-4 py-8 md:px-8">
        <PropertyList />
      </main>
    </RequirePermission>
  );
}
