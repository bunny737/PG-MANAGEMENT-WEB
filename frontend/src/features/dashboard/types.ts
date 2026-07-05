/** Shapes mirror the eventual `/api/v1/reports/occupancy/` and
 * `/api/v1/reports/financials/` responses (FE-D1/FE-D2) so swapping the mock
 * data module for a TanStack Query hook later needs no component changes.
 * Money fields are strings end-to-end per invariant F1. */

export interface OccupancySummary {
  totalBeds: number;
  occupiedBeds: number;
  vacantBeds: number;
  occupiedPercent: number;
  vacantPercent: number;
}

export interface FinancialsSummary {
  monthlyRevenue: string;
  revenueDelta: { direction: "up" | "down"; label: string };
  outstandingDues: string;
  securityDeposits: string;
}

export interface ActiveIssue {
  id: string;
  unit: string;
  issue: string;
  status: "open" | "in_progress" | "resolved";
}

/** Mirrors the eventual /api/v1/activity-timeline/?limit=n response (FE-16) —
 * `icon`/`tone` are a frontend-only rendering hint, not backend fields. */
export interface ActivityItem {
  id: string;
  tone: "info" | "good" | "neutral";
  text: string;
  timestamp: string;
}

export interface DashboardSummary {
  occupancy: OccupancySummary;
  financials: FinancialsSummary;
  issues: ActiveIssue[];
  highPriorityIssueCount: number;
  activity: ActivityItem[];
}
