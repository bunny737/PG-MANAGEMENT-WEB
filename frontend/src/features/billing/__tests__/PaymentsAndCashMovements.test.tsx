/* eslint-disable i18next/no-literal-string -- test fixtures, not UI copy */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, test, vi } from "vitest";
import billing from "@/messages/en/billing.json";
import common from "@/messages/en/common.json";
import status from "@/messages/en/status.json";

const api = vi.hoisted(() => ({
  listPaymentsFiltered: vi.fn(),
  deletePayment: vi.fn(),
  getReceipt: vi.fn(),
  downloadReceiptPdf: vi.fn(),
  getCashMovements: vi.fn(),
}));
const refresh = vi.hoisted(() => ({ afterPayment: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, ...api };
});
vi.mock("@/lib/refresh", () => refresh);
vi.mock("@/components/shared/PermissionGate", () => ({
  PermissionGate: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock("@/components/shared/PropertyFilter", () => ({
  PropertyFilter: () => null,
  useActiveProperty: () => ({ propertyId: null }),
}));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));

import { ApiError } from "@/lib/api";
import { CashMovementsList } from "../CashMovementsList";
import { PaymentsList } from "../PaymentsList";
import { ReceiptView } from "../ReceiptView";

function renderWithProviders(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale="en" messages={{ billing, common, status }}>
        {ui}
      </NextIntlClientProvider>
    </QueryClientProvider>
  );
}

describe("PaymentsList → advance adjustment labeling, filtering & deletion", () => {
  beforeEach(() => {
    for (const fn of [...Object.values(api), ...Object.values(refresh)]) fn.mockReset();
    refresh.afterPayment.mockResolvedValue(undefined);
    vi.spyOn(window, "confirm").mockReturnValue(true);
  });

  test("filters by advance_adjustment and displays Advance Adjustment without Cash fallback", async () => {
    api.listPaymentsFiltered.mockResolvedValue([
      {
        id: "pay-adj-1",
        receipt_number: "RCT-000020",
        invoice: "inv-2",
        invoice_period_start: "2026-12-01",
        invoice_period_end: "2026-12-31",
        resident: "r1",
        resident_name: "Kiran Verma",
        property: "p1",
        property_name: "Greenwood",
        room_number: "101",
        bed_number: "101-A",
        amount: "10000.00",
        payment_date: "2026-12-01",
        payment_mode: "",
        is_advance_adjustment: true,
        payment_source: "advance_adjustment",
        payment_source_label: "Advance adjustment",
        historical_collection_mode: "upi",
        reference: "Advance adjustment",
        recorded_by: null,
        recorded_by_name: null,
        created_at: "",
        updated_at: "",
      },
    ]);

    renderWithProviders(<PaymentsList />);

    expect(await screen.findByText("Kiran Verma")).toBeInTheDocument();
    // Mode cell shows Advance Adjustment + historical mode context, never Cash.
    const select = screen.getByRole("combobox");
    expect(screen.getAllByText(status.advance_adjustment).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("Collected via UPI")).toBeInTheDocument();

    fireEvent.change(select, { target: { value: "advance_adjustment" } });
    await waitFor(() =>
      expect(api.listPaymentsFiltered).toHaveBeenLastCalledWith(
        expect.objectContaining({ payment_mode: "advance_adjustment" })
      )
    );
  });

  test("deleting an advance adjustment confirms restoration and surfaces exit-reversal errors", async () => {
    api.listPaymentsFiltered.mockResolvedValue([
      {
        id: "pay-adj-2",
        receipt_number: "RCT-000021",
        invoice: "inv-2",
        invoice_period_start: "2026-12-01",
        invoice_period_end: "2026-12-31",
        resident: "r1",
        resident_name: "Kiran Verma",
        property: "p1",
        property_name: "Greenwood",
        room_number: null,
        bed_number: null,
        amount: "5000.00",
        payment_date: "2026-12-01",
        payment_mode: "",
        is_advance_adjustment: true,
        payment_source: "advance_adjustment",
        payment_source_label: "Advance adjustment",
        historical_collection_mode: null,
        reference: "Advance adjustment",
        recorded_by: null,
        recorded_by_name: null,
        created_at: "",
        updated_at: "",
      },
    ]);
    api.deletePayment.mockRejectedValueOnce(
      new ApiError(400, { code: "RESIDENT_NOT_CURRENT", detail: "Advance adjustments cannot be reversed after exit." })
    );

    renderWithProviders(<PaymentsList />);
    const deleteBtn = await screen.findByTitle(billing.payments.delete);
    fireEvent.click(deleteBtn);

    expect(window.confirm).toHaveBeenCalledWith(billing.payments.deleteAdjustmentConfirmBody);
    expect(await screen.findByRole("alert")).toHaveTextContent("Advance adjustments cannot be reversed after exit.");
  });
});

describe("ReceiptView → advance adjustment receipt", () => {
  beforeEach(() => {
    for (const fn of Object.values(api)) fn.mockReset();
  });

  test("shows Advance Adjustment, historical collection mode, and non-cash note when payment_mode is blank", async () => {
    api.getReceipt.mockResolvedValue({
      receipt_for: "pay-adj-1",
      receipt_number: "RCT-000030",
      resident: "Kiran Verma",
      resident_id: "r1",
      property: "p1",
      property_name: "Greenwood",
      room_number: "101",
      bed_number: "101-A",
      invoice: "inv-2",
      period_start: "2026-12-01",
      period_end: "2026-12-31",
      amount: "10000.00",
      payment_date: "2026-12-01",
      payment_mode: "",
      is_advance_adjustment: true,
      payment_source: "advance_adjustment",
      payment_source_label: "Advance adjustment",
      historical_collection_mode: "upi",
      reference: "Final month advance adjustment",
      recorded_by: "u1",
      recorded_by_name: "Owner",
      created_at: "",
      invoice_total: "10000.00",
      invoice_paid: "10000.00",
      invoice_balance_due: "0.00",
      invoice_status: "paid",
    });

    renderWithProviders(<ReceiptView id="pay-adj-1" />);

    expect(await screen.findByText(status.advance_adjustment)).toBeInTheDocument();
    expect(screen.getByText(billing.receipt.nonCashNote)).toBeInTheDocument();
    expect(screen.getByText(billing.receipt.originalMode)).toBeInTheDocument();
    expect(screen.getByText(status.upi)).toBeInTheDocument();
    expect(screen.queryByText(status.cash)).toBeNull();
  });
});

describe("CashMovementsList → admission advances, deposits, and limitation disclosure", () => {
  beforeEach(() => {
    for (const fn of Object.values(api)) fn.mockReset();
  });

  test("renders cash receipt rows by type, advance adjustments card, and refunds limitation notice", async () => {
    api.getCashMovements.mockResolvedValue({
      from: "2026-11-01",
      to: "2026-11-30",
      gross_receipts: "35000.00",
      refunds_paid: "0.00",
      advance_adjustments_total: "10000.00",
      total: "35000.00",
      count: 3,
      results: [
        {
          type: "admission_advance",
          id: "adm-1",
          date: "2026-11-01",
          amount: "20000.00",
          receipt_number: null,
          payment_mode: "",
          source_label: "Collected at admission",
          invoice: null,
          resident: "r1",
          resident_name: "Kiran Verma",
          property: "p1",
          property_name: "Greenwood",
        },
        {
          type: "deposit",
          id: "dep-1",
          date: "2026-11-01",
          amount: "5000.00",
          receipt_number: null,
          payment_mode: "bank_transfer",
          source_label: "Bank Transfer",
          invoice: null,
          resident: "r1",
          resident_name: "Kiran Verma",
          property: "p1",
          property_name: "Greenwood",
        },
        {
          type: "payment",
          id: "pay-1",
          date: "2026-11-10",
          amount: "10000.00",
          receipt_number: "RCT-000005",
          payment_mode: "upi",
          source_label: "UPI",
          invoice: "inv-2",
          resident: "r1",
          resident_name: "Kiran Verma",
          property: "p1",
          property_name: "Greenwood",
        },
      ],
    });

    renderWithProviders(<CashMovementsList />);

    const adjLabel = await screen.findByText(billing.cashMovements.advanceAdjustmentsTotal);
    expect(within(adjLabel.parentElement!).getByText("₹10,000.00")).toBeInTheDocument();
    expect(screen.getByText(billing.cashMovements.refundsLimitationNotice)).toBeInTheDocument();
    expect(screen.getByText(billing.cashMovements.type.admission_advance)).toBeInTheDocument();
    expect(screen.getByText(billing.cashMovements.type.deposit)).toBeInTheDocument();
    expect(screen.getByText(billing.cashMovements.type.payment)).toBeInTheDocument();
    expect(screen.getByText("Collected at admission")).toBeInTheDocument();
  });
});
