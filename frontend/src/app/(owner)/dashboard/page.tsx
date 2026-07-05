import { ActiveIssuesCard } from "@/features/dashboard/ActiveIssuesCard";
import { DashboardHeader } from "@/features/dashboard/DashboardHeader";
import { DesktopHeader } from "@/features/dashboard/DesktopHeader";
import { FinancialsCard } from "@/features/dashboard/FinancialsCard";
import { mockDashboardSummary } from "@/features/dashboard/mock-data";
import { OccupancyCard } from "@/features/dashboard/OccupancyCard";
import { QuickActions } from "@/features/dashboard/QuickActions";
import { TodaysActivity } from "@/features/dashboard/TodaysActivity";

// TODO(FE-D1/FE-D2): replace mockDashboardSummary with a TanStack Query hook
// against /api/v1/reports/... once backend modules 02/08/09/11 are wired up
// in the frontend. Component tree below is written against the same
// DashboardSummary shape so that swap touches this file only.
//
// Mobile (< md) and desktop (md+) render deliberately different layouts —
// they match two distinct reference designs (phone tab-bar mock vs. desktop
// sidebar mock), not just a reflow of the same one. See docs/frontend-plan.md
// §2.1 for what's shared (tokens, cards) vs. what differs (header, nav, grid).
export default function DashboardPage() {
  const { occupancy, financials, issues, highPriorityIssueCount, activity } =
    mockDashboardSummary;

  return (
    <>
      {/* Mobile */}
      <div className="mx-auto flex max-w-md flex-col gap-4 pb-6 md:hidden">
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

      {/* Desktop */}
      <div className="hidden md:block">
        <DesktopHeader />
        <div className="flex flex-col gap-6 p-8">
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-[2fr_1fr]">
            <OccupancyCard data={occupancy} />
            <FinancialsCard data={financials} />
          </div>
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-[2fr_1fr]">
            <ActiveIssuesCard
              issues={issues}
              highPriorityCount={highPriorityIssueCount}
            />
            <TodaysActivity items={activity} />
          </div>
        </div>
      </div>
    </>
  );
}
