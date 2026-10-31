/* eslint-disable i18next/no-literal-string -- test fixtures, not UI copy */
import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import type { Announcement, FoodHoliday, FoodHolidayCredit, FoodHolidayCredits } from "@/lib/api";
import { localDateKey } from "@/lib/date";
import common from "@/messages/en/common.json";
import notices from "@/messages/en/notices.json";
import status from "@/messages/en/status.json";

export const copy = notices;

export const PROPERTY_A = "7d6c0a52-0f4e-4d0c-9a53-3b1f6a6f7c11";
export const PROPERTY_B = "9b1f3c2e-5a64-4c2b-8f3d-2f6a1d0c9e22";
export const HOLIDAY_ID = "1c4f5a10-2b3d-4e5f-8a6b-7c8d9e0f1a2b";
export const NOTICE_ID = "5e6f7a80-1b2c-4d3e-9f4a-5b6c7d8e9f01";

export const PROPERTIES = [
  { id: PROPERTY_A, name: "Sunrise PG" },
  { id: PROPERTY_B, name: "Lakeview PG" },
];

/** "YYYY-MM-DD" for `offset` days from today. */
export function dayOffset(offset: number): string {
  const date = new Date();
  date.setDate(date.getDate() + offset);
  return localDateKey(date);
}

export function notice(overrides: Partial<Announcement> = {}): Announcement {
  return {
    id: NOTICE_ID,
    property: PROPERTY_A,
    property_name: "Sunrise PG",
    title: "Water supply cut",
    body: "No water on Sunday morning.",
    category: "maintenance",
    is_pinned: false,
    expires_on: null,
    is_auto_text: false,
    food_holiday: null,
    notice_outdated: false,
    created_by: null,
    created_by_name: "Asha",
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-01T00:00:00Z",
    ...overrides,
  };
}

export function holiday(overrides: Partial<FoodHoliday> = {}): FoodHoliday {
  return {
    id: HOLIDAY_ID,
    property: PROPERTY_A,
    property_name: "Sunrise PG",
    name: "Dasara",
    start_date: "2026-10-20",
    end_date: "2026-10-23",
    total_days: 4,
    adjust_in_bill: true,
    rate_per_day: "80.00",
    announcement: NOTICE_ID,
    notice_outdated: false,
    is_locked: false,
    credit_total: "400.00",
    credit_count: 1,
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-01T00:00:00Z",
    ...overrides,
  };
}

export function credit(overrides: Partial<FoodHolidayCredit> = {}): FoodHolidayCredit {
  return {
    id: "c1",
    resident: "r1",
    resident_name: "Ravi Kumar",
    status: "invoiced",
    days: 4,
    rate: "100.00",
    amount: "400.00",
    invoice: "i1",
    invoice_status: "draft",
    clawback_amount: "0.00",
    ...overrides,
  };
}

export function credits(rows: FoodHolidayCredit[], totals: Partial<FoodHolidayCredits["totals"]> = {}): FoodHolidayCredits {
  return {
    credits: rows,
    totals: {
      credited: "400.00",
      credited_count: 1,
      estimated: "0.00",
      estimated_count: 0,
      waived_count: 0,
      clawback: "0.00",
      ...totals,
    },
  };
}

/** A promise settled from the test, to hold a request open. */
export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

export function renderWithMessages(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale="en" messages={{ common, notices, status }}>
        {ui}
      </NextIntlClientProvider>
    </QueryClientProvider>
  );
}

export const OWNER = [
  "view_notices",
  "manage_notices",
  "view_finance",
  "manage_invoices",
  "manage_property_settings",
];
