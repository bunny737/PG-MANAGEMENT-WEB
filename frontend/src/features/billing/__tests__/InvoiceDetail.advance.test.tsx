/* eslint-disable i18next/no-literal-string -- test fixtures, not UI copy */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, test, vi } from "vitest";
import billing from "@/messages/en/billing.json";
import common from "@/messages/en/common.json";
import status from "@/messages/en/status.json";

const api = vi.hoisted(() => ({
  getInvoice: vi.fn(),
  getResident: vi.fn(),
  listPaymentsFiltered: vi.fn(),
  adjustInvoiceAdvance: vi.fn(),
  downloadReceiptPdf: vi.fn(),
}));
const refresh = vi.hoisted(() => ({
  afterPayment: vi.fn(),
  afterInvoiceChange: vi.fn(),
  afterInvoiceIssued: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, ...api };
});
vi.mock("@/lib/refresh", () => refresh);
vi.mock("@/components/shared/PermissionGate", () => ({
  PermissionGate: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));

import { InvoiceDetail } from "../InvoiceDetail";
import { ApiError } from "@/lib/api";

const ISSUED_INVOICE = {
  id: "inv-2",
  resident: "r1",
  resident_name: "Ananya Rao",
  property: "p1",
  property_name: "Sunrise PG",
  room_number: "202",
  bed_number: "202-A",
  period_start: "2026-12-01",
  period_end: "2026-12-31",
  billing_mode: "monthly",
  issue_date: "2026-12-01",
  due_date: "2026-12-06",
  status: "issued",
  notes: "",
  created_by: null,
  line_items: [{ id: "l1", line_type: "accommodation", label: "Rent", amount: "10000.00", order: 0 }],
  total: "10000.00",
  amount_paid: "0.00",
  balance_due: "10000.00",
  capped_allocated: "0.00",
  is_overdue: false,
  auto_generated: false,
  review_reasons: [] as string[],
  due_date_policy: "from_period_start",
  auto_issue_on: null,
  auto_issue_held: false,
  can_auto_issue: false,
  created_at: "",
  updated_at: "",
};

const RESIDENT = {
  id: "r1",
  status: "active",
  advance_amount: "20000.00",
  advance_applied_amount: "10000.00",
  advance_refundable: "10000.00",
  first_invoice_advance_settled: true,
};

async function renderDetail(invoiceOverrides: Partial<typeof ISSUED_INVOICE> = {}, residentOverrides: Partial<typeof RESIDENT> = {}) {
  api.getInvoice.mockResolvedValue({ ...ISSUED_INVOICE, ...invoiceOverrides });
  api.getResident.mockResolvedValue({ ...RESIDENT, ...residentOverrides });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale="en" messages={{ billing, common, status }}>
        <InvoiceDetail id={ISSUED_INVOICE.id} />
      </NextIntlClientProvider>
    </QueryClientProvider>
  );
  await screen.findByRole("heading", { name: ISSUED_INVOICE.resident_name });
}

describe("InvoiceDetail → Adjust from advance", () => {
  beforeEach(() => {
    for (const fn of [...Object.values(api), ...Object.values(refresh)]) fn.mockReset();
    api.listPaymentsFiltered.mockResolvedValue([]);
    refresh.afterPayment.mockResolvedValue(undefined);
  });

  test("shows Adjust from advance and held advance hint on issued invoice with held advance", async () => {
    await renderDetail();

    expect(await screen.findByRole("button", { name: billing.detail.adjustAdvance })).toBeEnabled();
    expect(screen.getByText(/Held advance available:/)).toBeInTheDocument();
  });

  test("disables Adjust from advance with first-invoice hint until first invoice is settled", async () => {
    await renderDetail({}, { first_invoice_advance_settled: false });

    const btn = await screen.findByRole("button", { name: billing.detail.adjustAdvance });
    expect(btn).toBeDisabled();
    expect(screen.getByText(billing.detail.firstInvoicePendingHint)).toBeInTheDocument();
  });

  test("hides Adjust from advance when invoice is draft or held advance is zero", async () => {
    const { unmount } = await (async () => {
      await renderDetail({ status: "draft" });
      return { unmount: () => document.body.replaceChildren() };
    })();
    expect(screen.queryByRole("button", { name: billing.detail.adjustAdvance })).toBeNull();
    unmount();

    await renderDetail({}, { advance_refundable: "0.00" });
    expect(screen.queryByRole("button", { name: billing.detail.adjustAdvance })).toBeNull();
  });

  test("supports partial custom adjustment, sends Idempotency-Key, refreshes, and shows receipt links", async () => {
    api.adjustInvoiceAdvance.mockResolvedValue({
      payment: {
        id: "pay-adj-1",
        receipt_number: "RCT-000010",
        amount: "4000.00",
        payment_mode: "upi",
        is_advance_adjustment: true,
        payment_source: "advance_adjustment",
        payment_source_label: "Advance adjustment",
        historical_collection_mode: "upi",
      },
      replayed: false,
    });

    await renderDetail({ balance_due: "10000.00" }, { advance_refundable: "8000.00" });
    fireEvent.click(await screen.findByRole("button", { name: billing.detail.adjustAdvance }));

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText(billing.adjustAdvance.nonCashNotice)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: billing.adjustAdvance.custom }));
    const amountInput = screen.getByLabelText(billing.adjustAdvance.amount) as HTMLInputElement;
    // Exceeding held advance is caught before API submission.
    fireEvent.change(amountInput, { target: { value: "9000.00" } });
    fireEvent.click(screen.getByRole("button", { name: billing.adjustAdvance.submit }));
    expect(await screen.findByText(billing.adjustAdvance.errExceedsHeld)).toBeInTheDocument();
    expect(api.adjustInvoiceAdvance).not.toHaveBeenCalled();

    fireEvent.change(amountInput, { target: { value: "4000.00" } });
    fireEvent.change(screen.getByLabelText(billing.adjustAdvance.note), { target: { value: "Part final month" } });
    fireEvent.click(screen.getByRole("button", { name: billing.adjustAdvance.submit }));

    await waitFor(() => expect(api.adjustInvoiceAdvance).toHaveBeenCalledTimes(1));
    expect(api.adjustInvoiceAdvance).toHaveBeenCalledWith(
      "inv-2",
      expect.objectContaining({
        amount: "4000.00",
        adjustment_date: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
        note: "Part final month",
      }),
      expect.any(String)
    );
    expect(refresh.afterPayment).toHaveBeenCalledWith({
      invoiceId: "inv-2",
      residentId: "r1",
      propertyId: "p1",
    });
    expect(await screen.findByText(billing.adjustAdvance.success)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: billing.adjustAdvance.viewReceipt })).toHaveAttribute(
      "href",
      "/billing/payments/pay-adj-1"
    );
  });

  test("handles FIRST_INVOICE_NOT_ISSUED and idempotent replay cleanly", async () => {
    api.adjustInvoiceAdvance.mockRejectedValueOnce(
      new ApiError(400, { code: "FIRST_INVOICE_NOT_ISSUED", detail: "Issue first invoice first." })
    );
    await renderDetail();
    fireEvent.click(await screen.findByRole("button", { name: billing.detail.adjustAdvance }));
    fireEvent.click(screen.getByRole("button", { name: billing.adjustAdvance.submit }));

    expect(await screen.findByText(billing.adjustAdvance.errFirstInvoiceNotIssued)).toBeInTheDocument();

    api.adjustInvoiceAdvance.mockResolvedValueOnce({
      payment: { id: "pay-adj-1", amount: "10000.00", receipt_number: "RCT-000011" },
      replayed: true,
    });
    fireEvent.click(screen.getByRole("button", { name: billing.adjustAdvance.submit }));
    expect(await screen.findByText(billing.adjustAdvance.replayed)).toBeInTheDocument();
  });

  test("labels advance adjustment payments cleanly without inventing Cash when payment_mode is blank", async () => {
    api.listPaymentsFiltered.mockResolvedValue([
      {
        id: "pay-adj-1",
        receipt_number: "RCT-000012",
        invoice: "inv-2",
        invoice_period_start: "2026-12-01",
        invoice_period_end: "2026-12-31",
        resident: "r1",
        resident_name: "Ananya Rao",
        property: "p1",
        property_name: "Sunrise PG",
        room_number: "202",
        bed_number: "202-A",
        amount: "10000.00",
        payment_date: "2026-12-01",
        payment_mode: "",
        is_advance_adjustment: true,
        payment_source: "advance_adjustment",
        payment_source_label: "Advance adjustment",
        historical_collection_mode: "bank_transfer",
        reference: "Advance adjustment",
        recorded_by: null,
        recorded_by_name: null,
        created_at: "",
        updated_at: "",
      },
    ]);
    await renderDetail();

    expect(await screen.findByText(status.advance_adjustment)).toBeInTheDocument();
    expect(screen.getByText(/Originally collected via Bank Transfer/)).toBeInTheDocument();
    expect(screen.queryByText(status.cash)).toBeNull();
  });

  test("requires an explicit adjustment date before submitting", async () => {
    await renderDetail();
    fireEvent.click(await screen.findByRole("button", { name: billing.detail.adjustAdvance }));
    const dateInput = await screen.findByLabelText(billing.adjustAdvance.date);
    fireEvent.change(dateInput, { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: billing.adjustAdvance.submit }));

    expect(await screen.findByText(billing.adjustAdvance.errDateRequired)).toBeInTheDocument();
    expect(api.adjustInvoiceAdvance).not.toHaveBeenCalled();
  });
});

