import { queryClient } from "@/lib/queryClient";
import { queryKeys } from "@/lib/queryKeys";

/**
 * Mutation -> refresh contract (UX roadmap). One helper per mutation that
 * touches money or occupancy, called by the dialog/screen that performs it.
 * Each invalidates every family the mutation's backend side effects can
 * change — see docs/ux-roadmap-backend.md's refresh-contract table for the
 * side effects this mirrors. `invalidateQueries` only marks matching
 * queries stale; mounted screens refetch and update without a navigation.
 */

function invalidate(...keys: readonly unknown[][]) {
  return Promise.all(keys.map((key) => queryClient.invalidateQueries({ queryKey: key })));
}

/** Record or delete a payment. */
export function afterPayment(opts: { invoiceId?: string; residentId?: string; propertyId?: string } = {}) {
  const keys: unknown[][] = [
    [...queryKeys.invoices.all],
    [...queryKeys.payments.all],
    [...queryKeys.cashMovements.all],
    [...queryKeys.analytics.all],
    [...queryKeys.dashboard.all],
  ];
  if (opts.invoiceId) keys.push([...queryKeys.invoices.detail(opts.invoiceId)]);
  if (opts.residentId) keys.push([...queryKeys.residents.detail(opts.residentId)]);
  if (opts.propertyId) keys.push([...queryKeys.properties.layout(opts.propertyId)]);
  return invalidate(...keys);
}

/** Issuing an invoice auto-records the admission advance as a payment, so
 * this refreshes everything afterPayment does too. */
export function afterInvoiceIssued(opts: { invoiceId?: string; residentId?: string; propertyId?: string } = {}) {
  return afterPayment(opts);
}

/** Create/edit/delete a draft invoice, or add/edit/remove a line item. */
export function afterInvoiceChange(opts: { invoiceId?: string; residentId?: string; propertyId?: string } = {}) {
  const keys: unknown[][] = [
    [...queryKeys.invoices.all],
    [...queryKeys.analytics.all],
    [...queryKeys.dashboard.all],
  ];
  if (opts.invoiceId) keys.push([...queryKeys.invoices.detail(opts.invoiceId)]);
  if (opts.residentId) keys.push([...queryKeys.residents.detail(opts.residentId)]);
  if (opts.propertyId) keys.push([...queryKeys.properties.layout(opts.propertyId)]);
  return invalidate(...keys);
}

/** Create or end a discount. */
export function afterDiscountChange(opts: { residentId?: string } = {}) {
  const keys: unknown[][] = [[...queryKeys.discounts.all]];
  if (opts.residentId) keys.push([...queryKeys.residents.detail(opts.residentId)]);
  return invalidate(...keys);
}

/** Bed status PATCH, room/bed add or delete. */
export function afterBedChange(opts: { propertyId?: string } = {}) {
  const keys: unknown[][] = [[...queryKeys.dashboard.all]];
  if (opts.propertyId) keys.push([...queryKeys.properties.layout(opts.propertyId)]);
  return invalidate(...keys);
}

/** Admission into a bed. */
export function afterAdmission(opts: { propertyId?: string } = {}) {
  const keys: unknown[][] = [[...queryKeys.residents.all], [...queryKeys.dashboard.all]];
  if (opts.propertyId) keys.push([...queryKeys.properties.layout(opts.propertyId)]);
  return invalidate(...keys);
}

/** Room/bed transfer. `fromPropertyId`/`toPropertyId` may be the same
 * property or two different ones (both refresh when they differ). */
export function afterTransfer(opts: {
  residentId?: string;
  fromPropertyId?: string;
  toPropertyId?: string;
} = {}) {
  const keys: unknown[][] = [[...queryKeys.residents.all], [...queryKeys.dashboard.all]];
  if (opts.residentId) keys.push([...queryKeys.residents.detail(opts.residentId)]);
  if (opts.fromPropertyId) keys.push([...queryKeys.properties.layout(opts.fromPropertyId)]);
  if (opts.toPropertyId && opts.toPropertyId !== opts.fromPropertyId) {
    keys.push([...queryKeys.properties.layout(opts.toPropertyId)]);
  }
  return invalidate(...keys);
}

/** Notice given/cancelled, vacate finalized, or absconded. */
export function afterVacate(opts: { residentId?: string; propertyId?: string } = {}) {
  const keys: unknown[][] = [[...queryKeys.residents.all], [...queryKeys.dashboard.all]];
  if (opts.residentId) keys.push([...queryKeys.residents.detail(opts.residentId)]);
  if (opts.propertyId) keys.push([...queryKeys.properties.layout(opts.propertyId)]);
  return invalidate(...keys);
}

/** Create/edit/delete an expense. Invalidating the whole `expenses` family
 * (not just the current month) covers an edit that moved the date to a
 * different month's list/summary — same reasoning as the roadmap's
 * "both old and new months" rule, done by invalidating broadly rather
 * than tracking which months were affected. */
export function afterExpenseChange() {
  return invalidate([...queryKeys.expenses.all], [...queryKeys.analytics.all]);
}
