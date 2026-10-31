/* eslint-disable i18next/no-literal-string -- test fixtures, not UI copy */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, test, vi } from "vitest";
import billing from "@/messages/en/billing.json";
import common from "@/messages/en/common.json";
import status from "@/messages/en/status.json";

const api = vi.hoisted(() => ({
  getInvoice: vi.fn(),
  listPaymentsFiltered: vi.fn(),
  deleteInvoiceLineItem: vi.fn(),
  addInvoiceLineItem: vi.fn(),
  updateInvoiceLineItem: vi.fn(),
}));
const refresh = vi.hoisted(() => ({ afterInvoiceChange: vi.fn(), afterInvoiceIssued: vi.fn() }));

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

const INVOICE = {
  id: "inv-1",
  resident: "r1",
  resident_name: "Ravi Kumar",
  property: "p1",
  property_name: "Sunrise PG",
  room_number: "101",
  bed_number: "101-A",
  period_start: "2026-11-01",
  period_end: "2026-11-30",
  billing_mode: "monthly",
  issue_date: null,
  due_date: "2026-11-06",
  status: "draft",
  notes: "",
  created_by: null,
  line_items: [
    { id: "l1", line_type: "accommodation", label: "Accommodation + Food (Monthly)", amount: "7000.00", order: 0 },
    { id: "l2", line_type: "food_holiday", label: "Food holiday: Dasara (4 days x ₹100)", amount: "-400.00", order: 1 },
  ],
  total: "6600.00",
  amount_paid: "0.00",
  balance_due: "6600.00",
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

async function renderDetail(invoice = INVOICE) {
  api.getInvoice.mockResolvedValue(invoice);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale="en" messages={{ billing, common, status }}>
        <InvoiceDetail id="inv-1" />
      </NextIntlClientProvider>
    </QueryClientProvider>
  );
  await screen.findByRole("heading", { name: INVOICE.resident_name });
  return view;
}

describe("InvoiceDetail → food-holiday credit line", () => {
  beforeEach(() => {
    for (const fn of [...Object.values(api), ...Object.values(refresh)]) fn.mockReset();
    api.listPaymentsFiltered.mockResolvedValue([]);
    vi.spyOn(window, "confirm").mockReturnValue(true);
  });

  test("is system-owned: no edit pencil, and Delete reads 'Waive'", async () => {
    const { container } = await renderDetail();

    expect(screen.getByText(billing.lineType.food_holiday)).toBeTruthy();
    expect(screen.getByRole("button", { name: billing.addLineDialog.waive })).toBeTruthy();
    // The ordinary accommodation line keeps its pencil (one); the credit line has none.
    expect(container.querySelectorAll("svg.lucide-pencil")).toHaveLength(1);
    // ...and its trash can (one): the credit line's delete is the Waive button.
    expect(container.querySelectorAll("svg.lucide-trash-2")).toHaveLength(1);
  });

  test("waiving confirms with the restore hint, deletes the line and refreshes invoices and holidays", async () => {
    api.deleteInvoiceLineItem.mockResolvedValue({ ...INVOICE, line_items: [INVOICE.line_items[0]] });
    await renderDetail();

    fireEvent.click(screen.getByRole("button", { name: billing.addLineDialog.waive }));
    await act(async () => {});

    expect(window.confirm).toHaveBeenCalledWith(billing.addLineDialog.waiveConfirm);
    expect(api.deleteInvoiceLineItem).toHaveBeenCalledWith("inv-1", "l2");
    expect(refresh.afterInvoiceChange).toHaveBeenCalledWith({
      invoiceId: "inv-1",
      residentId: "r1",
      propertyId: "p1",
    });
  });

  test("an issued invoice's credit line has no actions at all", async () => {
    const { container } = await renderDetail({ ...INVOICE, status: "issued" });

    expect(screen.queryByRole("button", { name: billing.addLineDialog.waive })).toBeNull();
    expect(container.querySelectorAll("svg.lucide-pencil")).toHaveLength(0);
  });
});
