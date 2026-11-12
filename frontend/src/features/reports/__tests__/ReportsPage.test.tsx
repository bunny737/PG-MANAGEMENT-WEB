/* eslint-disable i18next/no-literal-string -- test fixtures, not UI copy */
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, test, vi } from "vitest";
import common from "@/messages/en/common.json";
import reports from "@/messages/en/reports.json";
import status from "@/messages/en/status.json";

const state = vi.hoisted(() => ({
  tab: "overview",
  api: {
    getAnalyticsSummary: vi.fn(),
    getAnalyticsTrend: vi.fn(),
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(`tab=${state.tab}`),
}));
vi.mock("@/lib/session", () => ({
  useSession: () => ({ can: () => true }),
}));
vi.mock("@/components/shared/PropertyFilter", () => ({
  PropertyFilter: () => null,
  useActiveProperty: () => ({ propertyId: null }),
}));
vi.mock("@/components/shared/PermissionGate", () => ({
  PermissionGate: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock("../TrendChart", () => ({
  TrendChart: () => <div data-testid="trend-chart" />,
}));
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, ...state.api };
});

import { ReportsPage } from "../ReportsPage";

const SUMMARY = {
  month: "2026-11",
  property: null,
  timezones: ["Asia/Kolkata"],
  balances_as_of: "2026-11-15",
  ytd: { start: "2026-04-01", end: "2026-11-30" },
  occupancy: { total: 10, occupied: 8, reserved: 1, maintenance: 0, available: 1, occupancy_rate: 80.0 },
  finance: {
    gross_receipts: "25000.00",
    refunds_paid: "0.00",
    cash_collected: "25000.00",
    advance_adjustments_total: "10000.00",
    period_invoiced: "20000.00",
    period_collected: "20000.00",
    collection_rate: 100.0,
    outstanding_total: "0.00",
    period_outstanding: "0.00",
    overdue_total: "0.00",
    open_invoice_count: 0,
    residents_with_balance_count: 0,
    occupied_beds_with_balance_count: 0,
    deposits_held: "15000.00",
    ytd_cash_collected: "25000.00",
  },
  expenses: { expenses_paid: "5000.00", ytd_expenses_paid: "5000.00" },
  cash_flow: { net_cash_flow: "20000.00", ytd_net_cash_flow: "20000.00" },
  redacted: [],
};

function renderReports() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale="en" messages={{ common, reports, status }}>
        <ReportsPage />
      </NextIntlClientProvider>
    </QueryClientProvider>
  );
}

describe("ReportsPage → advance adjustments and net_cash_flow disclosure", () => {
  beforeEach(() => {
    state.tab = "overview";
    state.api.getAnalyticsSummary.mockReset().mockResolvedValue(SUMMARY);
    state.api.getAnalyticsTrend.mockReset().mockResolvedValue({
      end: "2026-11",
      months: 6,
      property: null,
      timezones: ["Asia/Kolkata"],
      series: [],
      redacted: [],
    });
  });

  test("overview shows the refunds limitation disclosure notice", async () => {
    renderReports();
    expect(await screen.findByText(reports.refundsLimitationNotice)).toBeInTheDocument();
  });

  test("collections tab shows Advance adjustments (non-cash) card and limitation disclosure", async () => {
    state.tab = "collections";
    renderReports();
    expect(await screen.findByText(reports.cards.advanceAdjustments)).toBeInTheDocument();
    expect(screen.getByText("₹10,000.00")).toBeInTheDocument();
    expect(screen.getByText(reports.refundsLimitationNotice)).toBeInTheDocument();
  });

  test("exports tab shows limitation disclosure under cash flow export", async () => {
    state.tab = "exports";
    renderReports();
    expect(await screen.findByText(reports.exports.pnl)).toBeInTheDocument();
    expect(screen.getByText(reports.refundsLimitationNotice)).toBeInTheDocument();
  });
});

