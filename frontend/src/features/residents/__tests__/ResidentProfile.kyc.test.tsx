/* eslint-disable i18next/no-literal-string -- test fixtures, not UI copy */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import common from "@/messages/en/common.json";
import residents from "@/messages/en/residents.json";
import status from "@/messages/en/status.json";
import { queryClient as appQueryClient } from "@/lib/queryClient";
import { afterPayment } from "@/lib/refresh";

const mocks = vi.hoisted(() => ({
  getResident: vi.fn(),
  listComplaints: vi.fn(),
  listVacates: vi.fn(),
  getVacateSettlementPreview: vi.fn(),
  createDepositPayment: vi.fn(),
  can: vi.fn(() => true),
  user: { value: null as { kyc_uploads_enabled?: boolean } | null },
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    getResident: mocks.getResident,
    listComplaints: mocks.listComplaints,
    listVacates: mocks.listVacates,
    getVacateSettlementPreview: mocks.getVacateSettlementPreview,
    createDepositPayment: mocks.createDepositPayment,
  };
});
vi.mock("@/lib/session", () => ({
  useSession: () => ({ can: mocks.can, user: mocks.user.value }),
}));
vi.mock("@/components/shared/PermissionGate", () => ({
  PermissionGate: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock("@/components/shared/ContactActions", () => ({ ContactActions: () => null }));
vi.mock("../FinanceCard", () => ({ FinanceCard: () => null }));
vi.mock("../TransferRoomDialog", () => ({ TransferRoomDialog: () => null }));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));

import { ResidentProfile } from "../ResidentProfile";

const RESIDENT = {
  id: "r1",
  first_name: "Ravi",
  last_name: "Kumar",
  phone: "9000000001",
  status: "active",
  aadhaar_number: "1234",
  aadhaar_document: "https://files.example.test/aadhaar.pdf",
  pan_document: null,
};

async function openDocumentsTab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale="en" messages={{ common, residents, status }}>
        <ResidentProfile id="r1" />
      </NextIntlClientProvider>
    </QueryClientProvider>
  );
  const documentsTab = await screen.findByRole("button", { name: new RegExp(residents.profile.tabs.documents) });
  fireEvent.click(documentsTab);
}

describe("ResidentProfile → documents tab and the KYC upload gate", () => {
  beforeEach(() => {
    mocks.getResident.mockReset().mockResolvedValue(RESIDENT);
    mocks.listComplaints.mockReset().mockResolvedValue([]);
  });

  test("uploads off: no file inputs and an explanation, but stored documents stay downloadable", async () => {
    mocks.user.value = { kyc_uploads_enabled: false };
    await openDocumentsTab();

    expect(document.querySelectorAll('input[type="file"]')).toHaveLength(0);
    expect(screen.getByText(residents.profile.documents.uploadsDisabled)).toBeTruthy();
    expect(screen.getByRole("link", { name: new RegExp(residents.profile.documents.download) }).getAttribute("href")).toBe(
      RESIDENT.aadhaar_document
    );
  });

  test("an older cached profile without the flag is treated as off", async () => {
    mocks.user.value = {};
    await openDocumentsTab();
    expect(document.querySelectorAll('input[type="file"]')).toHaveLength(0);
  });

  test("uploads on: both document slots can be uploaded to and there is no notice", async () => {
    mocks.user.value = { kyc_uploads_enabled: true };
    await openDocumentsTab();

    expect(document.querySelectorAll('input[type="file"]')).toHaveLength(2);
    expect(screen.queryByText(residents.profile.documents.uploadsDisabled)).toBeNull();
  });
});

describe("ResidentProfile → security deposit paid in parts", () => {
  beforeEach(() => {
    mocks.user.value = {};
    mocks.listComplaints.mockReset().mockResolvedValue([]);
  });

  const renderProfile = async (resident: object) => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    mocks.getResident.mockReset().mockResolvedValue({ ...RESIDENT, ...resident });
    render(
      <QueryClientProvider client={client}>
        <NextIntlClientProvider locale="en" messages={{ common, residents, status }}>
          <ResidentProfile id="r1" />
        </NextIntlClientProvider>
      </QueryClientProvider>
    );
    await screen.findByRole("heading", { name: `${RESIDENT.first_name} ${RESIDENT.last_name}` });
  };

  test("shows agreed, collected and pending, with a button to record the rest", async () => {
    await renderProfile({
      security_deposit_agreed: "5000.00", security_deposit_amount: "2000.00", security_deposit_pending: "3000.00",
    });

    expect(screen.getByText(residents.profile.overview.depositAgreed)).toBeTruthy();
    expect(screen.getByText("₹5,000.00")).toBeTruthy();
    expect(screen.getByText("₹2,000.00")).toBeTruthy();
    expect(screen.getByText("₹3,000.00")).toBeTruthy();
    expect(screen.getByRole("button", { name: residents.profile.overview.recordDeposit })).toBeTruthy();
  });

  test("nothing pending: no pending row and no record button", async () => {
    await renderProfile({
      security_deposit_agreed: "5000.00", security_deposit_amount: "5000.00", security_deposit_pending: "0.00",
    });

    expect(screen.queryByText(residents.profile.overview.depositPending)).toBeNull();
    expect(screen.queryByRole("button", { name: residents.profile.overview.recordDeposit })).toBeNull();
  });

  test("a vacated resident can't pay a deposit, so there is no record button", async () => {
    await renderProfile({
      status: "vacated", security_deposit_agreed: "5000.00", security_deposit_amount: "2000.00", security_deposit_pending: "3000.00",
    });

    expect(screen.queryByRole("button", { name: residents.profile.overview.recordDeposit })).toBeNull();
  });

  test("an older API without the agreed amount still shows what was collected", async () => {
    await renderProfile({ security_deposit_amount: "1500.00" });

    expect(screen.getAllByText("₹1,500.00").length).toBe(2); // agreed falls back to collected
    expect(screen.queryByRole("button", { name: residents.profile.overview.recordDeposit })).toBeNull();
  });

  test("the button opens the record-deposit dialog; recording reloads the profile", async () => {
    await renderProfile({
      security_deposit_agreed: "5000.00", security_deposit_amount: "2000.00", security_deposit_pending: "3000.00",
    });
    fireEvent.click(screen.getByRole("button", { name: residents.profile.overview.recordDeposit }));

    const submit = await screen.findByRole("button", { name: residents.profile.depositDialog.submit });
    mocks.getResident.mockClear();
    mocks.createDepositPayment.mockResolvedValue({ payment: { id: "p1" }, replayed: false });
    fireEvent.click(submit);

    expect(await screen.findByText(residents.profile.depositDialog.success)).toBeTruthy();
    await waitFor(() => expect(mocks.getResident).toHaveBeenCalledWith("r1"));
  });
});

describe("ResidentProfile → held advance and notice-period settlement preview", () => {
  beforeEach(() => {
    mocks.user.value = {};
    mocks.can.mockImplementation(() => true);
    mocks.listComplaints.mockReset().mockResolvedValue([]);
    mocks.listVacates.mockReset().mockResolvedValue([]);
    mocks.getVacateSettlementPreview.mockReset();
  });

  afterEach(() => {
    appQueryClient.clear();
  });

  const renderProfile = async (resident: object, client?: QueryClient) => {
    const queryClient = client ?? new QueryClient({ defaultOptions: { queries: { retry: false } } });
    mocks.getResident.mockReset().mockResolvedValue({ ...RESIDENT, ...resident });
    const view = render(
      <QueryClientProvider client={queryClient}>
        <NextIntlClientProvider locale="en" messages={{ common, residents, status }}>
          <ResidentProfile id="r1" />
        </NextIntlClientProvider>
      </QueryClientProvider>
    );
    await screen.findByRole("heading", { name: `${RESIDENT.first_name} ${RESIDENT.last_name}` });
    return { ...view, queryClient };
  };

  test("shows advance collected, applied, and remaining held balance on overview", async () => {
    await renderProfile({
      advance_amount: "20000.00",
      advance_applied_amount: "10000.00",
      advance_refundable: "10000.00",
    });

    expect(screen.getByText(residents.profile.overview.advanceCollected)).toBeTruthy();
    expect(screen.getByText(residents.profile.overview.advanceApplied)).toBeTruthy();
    expect(screen.getByText(residents.profile.overview.advanceRemaining)).toBeTruthy();
    expect(screen.getByText("₹20,000.00")).toBeTruthy();
    expect(screen.getAllByText("₹10,000.00").length).toBe(2);
  });

  test("shows read-only settlement preview during notice period with dues shown separately", async () => {
    mocks.listVacates.mockResolvedValue([
      { id: "vac-1", resident: "r1", is_open: true, is_cancelled: false, is_settled: false, actual_vacate_date: null },
    ]);
    mocks.getVacateSettlementPreview.mockResolvedValue({
      security_deposit_amount: "5000.00",
      advance_amount: "20000.00",
      advance_applied_amount: "10000.00",
      advance_refundable: "10000.00",
      maintenance_deduction: "500.00",
      actual_vacate_date: "2026-11-30",
      food_holiday_credit: "200.00",
      food_holiday_clawback_calculated: "0.00",
      food_holiday_clawback_recovered: "0.00",
      food_holiday_clawback_unrecovered: "0.00",
      refund_amount: "14700.00",
      outstanding_dues: "3000.00",
    });

    await renderProfile({
      status: "notice_period",
      advance_amount: "20000.00",
      advance_applied_amount: "10000.00",
      advance_refundable: "10000.00",
    });

    expect(await screen.findByText(residents.profile.settlementPreview.title)).toBeTruthy();
    expect(mocks.listVacates).toHaveBeenCalledWith({ resident: "r1" });
    expect(mocks.getVacateSettlementPreview).toHaveBeenCalledWith("vac-1");
    expect(screen.getByText(residents.profile.settlementPreview.estimatedRefund)).toBeTruthy();
    expect(screen.getByText("₹14,700.00")).toBeTruthy();
    expect(screen.getByText(residents.profile.settlementPreview.outstandingDues)).toBeTruthy();
    expect(screen.getByText("₹3,000.00")).toBeTruthy();
    expect(screen.getByText(residents.profile.settlementPreview.outstandingSeparateNote)).toBeTruthy();
  });

  test("hides settlement preview when caller lacks manage_deposits", async () => {
    mocks.can.mockImplementation((perm?: string) => perm !== "manage_deposits");
    await renderProfile({ status: "notice_period", advance_amount: "10000.00" });

    expect(mocks.listVacates).not.toHaveBeenCalled();
    expect(screen.queryByText(residents.profile.settlementPreview.title)).toBeNull();
  });

  test("refreshes held advance and settlement preview after payment invalidation, focus, and remount", async () => {
    const openVacates = [
      { id: "vac-1", resident: "r1", is_open: true, is_cancelled: false, is_settled: false, actual_vacate_date: null },
    ];
    mocks.listVacates.mockResolvedValue(openVacates);
    mocks.getVacateSettlementPreview.mockResolvedValue({
      security_deposit_amount: "5000.00",
      advance_amount: "20000.00",
      advance_applied_amount: "10000.00",
      advance_refundable: "10000.00",
      maintenance_deduction: "0.00",
      actual_vacate_date: "2026-11-30",
      food_holiday_credit: "0.00",
      food_holiday_clawback_calculated: "0.00",
      food_holiday_clawback_recovered: "0.00",
      food_holiday_clawback_unrecovered: "0.00",
      refund_amount: "15000.00",
      outstanding_dues: "10000.00",
    });

    appQueryClient.clear();
    const { unmount } = await renderProfile(
      {
        status: "notice_period",
        advance_amount: "20000.00",
        advance_applied_amount: "10000.00",
        advance_refundable: "10000.00",
      },
      appQueryClient
    );
    expect(await screen.findByText("₹15,000.00")).toBeTruthy();

    // Another screen applies the remaining ₹10,000 advance and runs afterPayment().
    mocks.getResident.mockResolvedValue({
      ...RESIDENT,
      status: "notice_period",
      advance_amount: "20000.00",
      advance_applied_amount: "20000.00",
      advance_refundable: "0.00",
    });
    mocks.getVacateSettlementPreview.mockResolvedValue({
      security_deposit_amount: "5000.00",
      advance_amount: "20000.00",
      advance_applied_amount: "20000.00",
      advance_refundable: "0.00",
      maintenance_deduction: "0.00",
      actual_vacate_date: "2026-11-30",
      food_holiday_credit: "0.00",
      food_holiday_clawback_calculated: "0.00",
      food_holiday_clawback_recovered: "0.00",
      food_holiday_clawback_unrecovered: "0.00",
      refund_amount: "5000.00",
      outstanding_dues: "0.00",
    });

    await act(async () => {
      await afterPayment({ invoiceId: "inv-2", residentId: "r1", propertyId: "p1" });
    });
    await waitFor(() => expect(screen.getByText("₹5,000.00")).toBeTruthy());

    // Regaining window focus refreshes latest server state even without cache invalidation.
    mocks.getResident.mockResolvedValue({
      ...RESIDENT,
      status: "notice_period",
      advance_amount: "20000.00",
      advance_applied_amount: "14000.00",
      advance_refundable: "6000.00",
    });
    mocks.getVacateSettlementPreview.mockResolvedValue({
      security_deposit_amount: "5000.00",
      advance_amount: "20000.00",
      advance_applied_amount: "14000.00",
      advance_refundable: "6000.00",
      maintenance_deduction: "0.00",
      actual_vacate_date: "2026-11-30",
      food_holiday_credit: "0.00",
      food_holiday_clawback_calculated: "0.00",
      food_holiday_clawback_recovered: "0.00",
      food_holiday_clawback_unrecovered: "0.00",
      refund_amount: "11000.00",
      outstanding_dues: "6000.00",
    });
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
    });
    await waitFor(() => expect(screen.getByText("₹11,000.00")).toBeTruthy());

    // Moving away to Billing and back (unmount -> remount on shared QueryClient within 30s) still refetches.
    unmount();
    mocks.getResident.mockResolvedValue({
      ...RESIDENT,
      status: "notice_period",
      advance_amount: "20000.00",
      advance_applied_amount: "20000.00",
      advance_refundable: "0.00",
    });
    mocks.getVacateSettlementPreview.mockResolvedValue({
      security_deposit_amount: "5000.00",
      advance_amount: "20000.00",
      advance_applied_amount: "20000.00",
      advance_refundable: "0.00",
      maintenance_deduction: "0.00",
      actual_vacate_date: "2026-11-30",
      food_holiday_credit: "0.00",
      food_holiday_clawback_calculated: "0.00",
      food_holiday_clawback_recovered: "0.00",
      food_holiday_clawback_unrecovered: "0.00",
      refund_amount: "5000.00",
      outstanding_dues: "0.00",
    });
    render(
      <QueryClientProvider client={appQueryClient}>
        <NextIntlClientProvider locale="en" messages={{ common, residents, status }}>
          <ResidentProfile id="r1" />
        </NextIntlClientProvider>
      </QueryClientProvider>
    );
    await waitFor(() => expect(screen.getByText("₹5,000.00")).toBeTruthy());
  });
});
