import type { DashboardSummary } from "./types";

// Placeholder data for FE-00 visual scaffolding. Replaced by a TanStack Query
// hook against /api/v1/reports/... once backend modules 02/08/09/11 are wired
// (see FE-D1/FE-D2 in docs/frontend-plan.md).
export const mockDashboardSummary: DashboardSummary = {
  occupancy: {
    totalBeds: 120,
    occupiedBeds: 98,
    vacantBeds: 22,
    occupiedPercent: 81.6,
  },
  financials: {
    monthlyRevenue: "$42,500",
    revenueDelta: { direction: "up", label: "+5.2% vs last month" },
    outstandingDues: "$3,200",
    securityDeposits: "$18,000",
  },
  issues: [
    { id: "1", unit: "104A", issue: "AC not cooling", status: "open" },
  ],
  highPriorityIssueCount: 3,
};
