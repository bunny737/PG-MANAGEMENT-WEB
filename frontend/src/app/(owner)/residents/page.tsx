import { RequirePermission } from "@/components/shared/RequirePermission";
import { ResidentsDirectory } from "@/features/residents/ResidentsDirectory";

export default function ResidentsPage() {
  return (
    <RequirePermission permission="view_resident_profile">
      <main className="mx-auto w-full max-w-5xl px-4 py-8 md:px-8">
        <ResidentsDirectory />
      </main>
    </RequirePermission>
  );
}
