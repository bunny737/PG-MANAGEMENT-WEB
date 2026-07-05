import { ActiveIssuesCard } from "@/features/dashboard/ActiveIssuesCard";
import { DashboardHeader } from "@/features/dashboard/DashboardHeader";
import { FinancialsCard } from "@/features/dashboard/FinancialsCard";
import { mockDashboardSummary } from "@/features/dashboard/mock-data";
import { OccupancyCard } from "@/features/dashboard/OccupancyCard";
import { QuickActions } from "@/features/dashboard/QuickActions";

// TODO(FE-D1/FE-D2): replace mockDashboardSummary with a TanStack Query hook
// against /api/v1/reports/... once backend modules 02/08/09/11 are wired up
// in the frontend. Component tree below is written against the same
// DashboardSummary shape so that swap touches this file only.
export default function DashboardPage() {
  const { occupancy, financials, issues, highPriorityIssueCount } =
    mockDashboardSummary;

  return (
    <div className="mx-auto flex max-w-md flex-col gap-4 pb-6">
      <DashboardHeader />
      <QuickActions />
      <div className="flex flex-col gap-4 px-4">
        <OccupancyCard data={occupancy} />
        <FinancialsCard data={financials} />
        <ActiveIssuesCard
          issues={issues}
          highPriorityCount={highPriorityIssueCount}
        />
      </div>
    </div>
  );
}
