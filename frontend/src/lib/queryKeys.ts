/**
 * Central query-key factory. Every list/detail query builds its key from
 * here so the refresh contract (lib/refresh.ts) can invalidate exactly the
 * right family without the two files drifting apart on string literals.
 *
 * Convention: `[module, "list", filters?]` for a filtered list, `[module,
 * "detail", id]` for one record. A bare `[module]` prefix invalidates
 * every query for that module (list and detail together).
 */
export const queryKeys = {
  invoices: {
    all: ["invoices"] as const,
    list: (filters: Record<string, unknown> = {}) => ["invoices", "list", filters] as const,
    detail: (id: string) => ["invoices", "detail", id] as const,
    outstanding: (filters: Record<string, unknown> = {}) => ["invoices", "outstanding", filters] as const,
  },
  payments: {
    all: ["payments"] as const,
    list: (filters: Record<string, unknown> = {}) => ["payments", "list", filters] as const,
    detail: (id: string) => ["payments", "detail", id] as const,
    receipt: (id: string) => ["payments", "receipt", id] as const,
  },
  cashMovements: {
    all: ["cashMovements"] as const,
    list: (filters: Record<string, unknown> = {}) => ["cashMovements", "list", filters] as const,
  },
  discounts: {
    all: ["discounts"] as const,
    list: (filters: Record<string, unknown> = {}) => ["discounts", "list", filters] as const,
  },
  residents: {
    all: ["residents"] as const,
    list: (filters: Record<string, unknown> = {}) => ["residents", "list", filters] as const,
    detail: (id: string) => ["residents", "detail", id] as const,
  },
  properties: {
    all: ["properties"] as const,
    list: ["properties", "list"] as const,
    detail: (id: string) => ["properties", "detail", id] as const,
    layout: (id: string, period?: string) => ["properties", "layout", id, period] as const,
  },
  rooms: {
    all: ["rooms"] as const,
    detail: (id: string) => ["rooms", "detail", id] as const,
  },
  beds: {
    all: ["beds"] as const,
    detail: (id: string) => ["beds", "detail", id] as const,
  },
  expenses: {
    all: ["expenses"] as const,
    list: (filters: Record<string, unknown> = {}) => ["expenses", "list", filters] as const,
    summary: (filters: Record<string, unknown> = {}) => ["expenses", "summary", filters] as const,
    categories: ["expenses", "categories"] as const,
  },
  analytics: {
    all: ["analytics"] as const,
    summary: (filters: Record<string, unknown> = {}) => ["analytics", "summary", filters] as const,
    trend: (filters: Record<string, unknown> = {}) => ["analytics", "trend", filters] as const,
  },
  dashboard: {
    all: ["dashboard"] as const,
  },
};
