# Module: Payments

> Keep this file in sync with the code AT ALL TIMES.
> If the code and this file disagree, this file is wrong — fix it in the same commit.

**Status:** Done
**Phase:** 2
**PRD reference:** Module 10 (Payment Management)
**Depends on:** 08
**Blocks:** 14, 17

## Purpose
Owner/Manager manually records a resident's payment against an issued invoice
(Razorpay is never used for resident payments — invariant/PRD constraint).
Multiple partial payments may be recorded against one invoice; the invoice's
`status` auto-updates (issued → partially_paid → paid) from the sum received.
Deleting a payment (a correction) reverts the status. A receipt is available
per payment, and an outstanding-dues view lists every invoice still owed.

## Data model (as-built)

```
Table: payments                                 (RLS enforced, app: apps.billing)
  id                uuid PK
  tenant_id         uuid              (RLS)
  invoice           FK -> invoices.Invoice (PROTECT)
  amount            decimal(12,2)     (always positive)
  payment_date      date
  payment_mode      upi | cash | bank_transfer | card | cheque
  reference         varchar(255), blank   (txn ref / note, optional)
  recorded_by       FK -> users, null (SET_NULL)
  created_at / updated_at
```
Also added this module — computed (never stored) helpers on `Invoice`:
- `amount_paid` — sum of `payments` (Decimal).
- `balance_due` — `total - amount_paid`.
- `recompute_status()` — syncs `status` to payments received; a no-op on a
  draft invoice (not yet a financial obligation).
`is_overdue` (Module 08) now also treats `partially_paid` as overdue-eligible
(previously only `issued`).

## API endpoints
```
GET|POST         /api/v1/payments/                record / list payments        manage_payments
GET|DELETE       /api/v1/payments/{id}/            detail / delete (correction)  manage_payments
GET              /api/v1/payments/{id}/receipt/    receipt for one payment       manage_payments
GET              /api/v1/invoices/outstanding/     invoices with balance > 0     manage_invoices
```
No `PATCH` on payments — a financial record is corrected by deleting and
re-recording, matching the "issued invoice is immutable" discipline from
Module 08.

## Business rules (each maps to a test)
1. A payment may only be recorded against an **issued** or **partially_paid**
   invoice — a draft is not yet a financial obligation (`invoice_not_issued`).
2. A payment is rejected if the invoice is already **fully paid**
   (`invoice_fully_paid`), or if `amount` exceeds the outstanding
   `balance_due` (`overpayment`) — `balance_due` never goes negative
   (see Decisions).
3. `amount` must be greater than zero (`invalid_amount`).
4. Multiple partial payments accumulate; `Invoice.recompute_status()` sets
   `partially_paid` while `0 < amount_paid < total`, `paid` once
   `amount_paid >= total`.
5. Deleting a payment (a correction) recomputes the invoice status back down
   (`paid` → `partially_paid` → `issued`).
6. `recorded_by` is stamped from the request user server-side.
7. Recording and deleting a payment are audit logged
   (`payment.recorded` / `payment.deleted`).
8. `/payments/{id}/receipt/` returns resident, invoice period, amount, mode,
   reference, recorded-by, and the invoice's total/balance/status —
   "auto-generated receipt" (PRD). JSON for now; PDF rendering is Module 17's
   concern.
9. `/invoices/outstanding/` lists every issued/partially_paid invoice with
   `balance_due > 0` — "outstanding dues view across all residents" (PRD).
10. `manage_payments` (Super Admin, Owner, Manager) gates everything;
    Receptionist/Resident get 403. Scoped to the actor's assigned properties.
11. `payments` is RLS-enforced (isolation proven).

## Permissions
- `manage_payments` (Super Admin, Owner, Manager): all endpoints, scoped to
  assigned properties for Manager.
- Receptionist and Resident: no access.

## Edge cases handled
- `is_overdue` (Module 08) now also considers a `partially_paid` invoice past
  its due date overdue, not just `issued`.
- Deleting the only payment on a `paid` invoice reverts it to `issued`
  (0 paid → back to the un-paid state, not `partially_paid`).
- `Invoice.recompute_status()` is a no-op on a draft invoice, so nothing in
  Module 08's draft workflow is disturbed by this module.

## Open questions / Decisions
- [DECISION 2026-07-04] **Overpayment is rejected, not allowed as credit.**
  The PRD is silent on overpayment. Rejecting it keeps `balance_due >= 0` and
  the status state machine (`issued`/`partially_paid`/`paid`) exhaustive with
  no "credit balance" case to represent. A resident who pays extra by mistake
  is a manual, out-of-band correction (e.g. a discount or adjustment line on
  a future invoice); it is not modeled as invoice credit in MVP. Advances
  collected at admission are a distinct concept (Module 10 deposits/advance),
  not overpayment of a rent invoice.
- [DECISION 2026-07-04] **No `PATCH` on Payment.** Consistent with an issued
  Invoice being an immutable financial record (Module 08): a payment is
  corrected by deleting it (status recomputes) and recording a fresh one.
  Simpler than reconciling a partial edit against the status machine.
- [DECISION 2026-07-04] **`Payment` lives in `apps.billing`**, not a new app —
  same rationale as Module 08's `Invoice`/`Discount` placement: it is a small
  model tightly coupled to `Invoice` with no independent lifecycle.
- [DECISION 2026-07-04] **Receipt is a JSON endpoint, not a PDF**, in this
  module. PRD Module 14 ("Invoice and receipt PDF templates... in the
  selected language") is the natural home for PDF rendering; building it here
  would duplicate work once Module 17/14 lands.
- [OPEN] Full payment history per resident (PRD "Payment Features") is
  covered by `GET /payments/?invoice__resident=<id>` (filterable) — no
  dedicated resident-scoped endpoint yet; revisit if the frontend needs one
  shaped differently.

## Changelog
- 2026-06-xx  Created stub.
- 2026-07-04  Built: `Payment` model (RLS) in `apps.billing`; `Invoice`
  gained computed `amount_paid`/`balance_due` and `recompute_status()`.
  `record_payment`/`delete_payment` services drive the issued → partially_paid
  → paid state machine (and back down on deletion). `PaymentViewSet`
  (record/list/detail/delete + receipt action), `/invoices/outstanding/`
  action. Draft-invoice and overpayment guards. Audit logged. 20 new tests
  (recording, deletion/reversion, outstanding dues, receipt, scoping, RLS
  isolation); full suite (216) green. Spec written to as-built.
