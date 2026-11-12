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
  payment_mode      upi | cash | bank_transfer | card | cheque, blank
                    -- holds direct mode, or historical collection mode for
                    -- legacy/admission advance rows; blank allowed when is_advance_adjustment=True
  is_advance_adjustment  boolean, default false, indexed
                    -- true for automatic first-invoice drawdown & explicit "Adjust from advance"
  reference         varchar(255), blank   (txn ref / note, optional)
  recorded_by       FK -> users, null (SET_NULL)
  receipt_number    varchar(20), null  UNIQUE (tenant_id, receipt_number)
  idempotency_key   varchar(100), null UNIQUE (tenant_id, key) WHERE NOT NULL
  created_at / updated_at
  constraint payment_mode_required_for_direct: CHECK (is_advance_adjustment OR payment_mode <> '')

Table: receipt_counters                         (RLS enforced, 2026-10-16)
  id, tenant_id (UNIQUE), last_number
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
GET|POST         /api/v1/payments/                       record / list payments        manage_payments
GET|DELETE       /api/v1/payments/{id}/                   detail / delete (correction)  manage_payments
GET              /api/v1/payments/{id}/receipt/           receipt JSON; ?filetype=pdf   view_finance
POST             /api/v1/invoices/{id}/adjust-advance/    adjust held admission advance manage_payments
GET              /api/v1/invoices/outstanding/            invoices with balance > 0     view_finance
GET              /api/v1/cash-movements/                  cash receipts for a range     view_finance
```
`/payments/` list filters (2026-10-16, D3; extended 2026-11-11): `?invoice=&resident=&property=
&payment_mode=&is_advance_adjustment=&month=YYYY-MM&from=&to=&search=` (`invoice__resident` kept for
existing clients; `payment_mode=advance_adjustment` filters `is_advance_adjustment=True`, while cash/upi/etc.
filter `is_advance_adjustment=False`). Rows carry `receipt_number, resident, resident_name,
property, property_name, room_number, bed_number, invoice_period_start/end, is_advance_adjustment,
payment_source, payment_source_label, historical_collection_mode, recorded_by_name`. `POST /payments/`
and `POST /invoices/{id}/adjust-advance/` accept an `Idempotency-Key` header.
`/cash-movements/?property=&month=|from=&to=` returns `{from, to,
gross_receipts, refunds_paid, advance_adjustments_total, total, count, results[]}` — the drill-down of
the analytics `cash_collected` figure (Module 21). Each row has `type: payment | admission_advance | deposit`
plus `source_label` (non-cash `is_advance_adjustment=True` rows are excluded from `results[]`/`gross_receipts`
and summed separately in `advance_adjustments_total`).
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
12. (2026-10-16) Two concurrent payments that each fit the balance but together
    exceed it: exactly one succeeds (`ConcurrentOverpaymentTests`).
13. (2026-10-16) `Idempotency-Key`: a retry with the same key returns the
    original payment (200, `Idempotent-Replayed: true`) even if the invoice is
    now fully paid; the same key with any different persisted input (invoice,
    amount, payment date, mode or reference) is 409 `IDEMPOTENCY_KEY_REUSED`
    (2026-10-17: previously only invoice/amount were compared). Keys are
    unique per tenant (`unique_payment_idempotency_key`).
14. (2026-10-16) Every new payment gets a per-tenant sequential
    `receipt_number` (`RCT-000001`…) under the `receipt_counters` row lock;
    numbers are never reused, even after a payment is deleted. Existing
    payments were backfilled in recorded order (`billing.0006`).
15. (2026-10-16) `/receipt/?filetype=pdf` renders a translated A5 PDF
    (WeasyPrint, `billing/receipt.html`); the JSON gained `receipt_number`,
    property/room/bed, `invoice_paid`, `recorded_by_name`, `created_at`.

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
- [DECISION 2026-07-04] Build-order Module 14 (Notifications) added the PRD's
  "Payment receipt to resident" email (distinct from this module's own JSON
  receipt action above) — fires from `services.record_payment`, after the
  payment row and audit log are written, deferred via `transaction.on_commit`
  + Celery.
- [DECISION 2026-09-10] **Overpayment/status checks are authoritative in the
  service under a row lock, not just the serializer.** The serializer keeps a
  friendly pre-check, but two concurrent payments each within `balance_due`
  could together overpay it (and flip status to `paid`) because that read was
  not held under a lock. `record_payment` and `delete_payment` now
  `select_for_update()` the invoice and re-check draft/fully-paid/overpayment
  before writing, so the balance check and the payment insert are atomic.
- [DECISION 2026-10-16] **Idempotency key lives on the payment row** (partial
  unique index on `tenant_id, idempotency_key`) rather than a separate key
  store: the guarantee is transactional with the insert and needs no expiry.
  The replay check runs both before validation (so a retry of a payment that
  fully paid the invoice isn't rejected) and again under the invoice lock.
- [DECISION 2026-10-16] **Receipt stays JSON by default; PDF via
  `?filetype=pdf`** — the JSON contract already had consumers. The original
  "PDF is Module 14/17's concern" decision is superseded: the PDF reuses the
  Module 17 WeasyPrint renderer.
- [DECISION 2026-10-16] Receipt number format `RCT-` + 6 digits, per tenant,
  not per property or financial year — simplest unique, human-quotable id.
- [DECISION 2026-10-17] **Schema annotations for the web client.**
  `/cash-movements/` and `GET /payments/{id}/receipt/` build a plain dict by
  hand, so `/api/schema/` described them as an untyped `{}`. Both now carry
  `@extend_schema(responses=...)` pointing at schema-only serializers in the
  new `apps/billing/schema.py` (never instantiated for a real response) —
  see Module 21's 2026-10-17 decision for the full list and the test that
  guards it.

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
- 2026-07-04  Build-order Module 14 added an email-receipt dispatch to
  `services.record_payment` — no other change to payment recording itself.
- 2026-10-04  The admission advance now appears as an auto-recorded Payment on
  the resident's first issued invoice (see Module 08 changelog); security
  deposits are never payments.
- 2026-10-12  Payment viewset split the same way: reads (incl. `receipt`) need `view_finance`,
  writes `manage_payments`. See Module 01 `[DECISION 2026-10-12]`.
- 2026-10-16  UX roadmap D3/D4: list filters + resident context columns,
  `/cash-movements/`, `Idempotency-Key`, `receipt_number` + `ReceiptCounter`
  (RLS) + backfill migration, PDF receipt, concurrency test. Tests:
  `billing/tests/test_list_filters.py`, `test_payment_integrity.py`.
- 2026-11-11  Held advance balance adjustments & cash receipts integrity (Milestone 1):
  - `Payment.is_advance_adjustment` (migration `billing.0011_payment_is_advance_adjustment`) + blankable `payment_mode` (`payment_mode_required_for_direct` CHECK constraint). Never falls back to `'cash'`; exposes `payment_source` (`'advance_adjustment'` or mode), `payment_source_label` (`"Advance Adjustment"`), and `historical_collection_mode` across serializers, receipts (JSON + HTML/PDF), exports, and `PaymentsList`.
  - Pre-deployment read-only audit command `manage.py audit_historical_cash_ledger` + shared classifier (`apps/billing/historical_audit.py`) with a **hard fail-loud gate** inside `billing.0011` (`GATE_FAILURE` aborts migration instead of guessing/skipping ambiguous historical applied advances; `MANUAL_CONFLICT` rows with `"Advance collected at admission"` failing invariants remain `is_advance_adjustment=False`). Read-only inspection also reports deposit ledger mismatches (`security_deposit_amount != SUM(deposit_payments)`) and missing `advance_collected_date` without synthesizing `DepositPayment` rows.
  - `POST /api/v1/invoices/{id}/adjust-advance/` (`services.adjust_from_advance`) locks Settings → Resident → Invoice → Admission, requires `Active` or `Notice Period` (`resident_not_current`) and `first_invoice_advance_settled=True` (`first_invoice_not_issued`), atomically increments `advance_applied_amount`, creates `Payment(is_advance_adjustment=True)`, recomputes invoice status, and supports `Idempotency-Key` (`audit` logged).
  - `delete_payment` checks `is_advance_adjustment=True` (never legacy reference text) to restore `Admission.advance_applied_amount`, blocking reversal after exit (`resident_not_current`).
  - `CashMovementView` (`/cash-movements/`) sums direct payments (`is_advance_adjustment=False`), admission advances (`COALESCE(advance_collected_date, joining_date)`), and `DepositPayment`s; reports non-cash adjustments separately in `advance_adjustments_total` and keeps `refunds_paid = 0.00` (with explicit limitation notice in UI/exports). Tests: `billing/tests/test_advance_backfill_migration.py`, `billing/tests/test_payment_integrity.py`, `billing/tests/test_invoices.py`, `billing/tests/test_list_filters.py`.
- 2026-11-12  Review fix (cross-midnight idempotency on advance adjustments):
  - `InvoiceAdjustAdvanceSerializer` now requires an explicit `adjustment_date` (matching `PaymentWriteSerializer`), eliminating date drift across midnight when HTTP clients retry with an `Idempotency-Key`; `AdjustAdvanceDialog` validates `adjustment_date` (`adjustAdvance.errDateRequired`) and always sends it explicitly.
  - Direct Python callers of `services.adjust_from_advance(..., adjustment_date=None, idempotency_key=...)` compare replay retries against `timezone.localdate(existing.created_at)` instead of recomputing `local_today()`. Tests: `billing/tests/test_invoices.py`, frontend `InvoiceDetail.advance.test.tsx`.
