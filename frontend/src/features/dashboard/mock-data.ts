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
    vacantPercent: 18.4,
  },
  financials: {
    monthlyRevenue: "₹42,500",
    revenueDelta: { direction: "up", label: "+5.2% vs last month" },
    outstandingDues: "₹3,200",
    securityDeposits: "₹18,000",
  },
  issues: [
    { id: "1", unit: "104A", issue: "AC not cooling", status: "open" },
    { id: "2", unit: "212B", issue: "Wi-Fi connection drops", status: "in_progress" },
    { id: "3", unit: "301C", issue: "Leaking faucet in bathroom", status: "open" },
  ],
  highPriorityIssueCount: 3,
  activity: [
    {
      id: "1",
      tone: "info",
      text: "New resident **Rahul S.** checked into Unit 105B.",
      timestamp: "10:45 AM",
    },
    {
      id: "2",
      tone: "good",
      text: "Rent payment received for Unit 201A (₹450).",
      timestamp: "09:12 AM",
    },
    {
      id: "3",
      tone: "neutral",
      text: "Visitor logged for Unit 304 (Guest of Amit K.).",
      timestamp: "Yesterday, 8:30 PM",
    },
  ],
};
