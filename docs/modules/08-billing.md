# Module: Invoices / Billing

> Keep this file in sync with the code AT ALL TIMES.
> If the code and this file disagree, this file is wrong — fix it in the same commit.

**Status:** Done
**Phase:** 2
**PRD reference:** Module 9 (Rent & Billing)
**Depends on:** 06, 07
**Blocks:** 09, 10, 14, 17

## Purpose
Owner/Manager generate a resident's invoice for a billing period. The engine
builds it as a **list of line items** (invariant 6): accommodation from the
resident's contracted rent (invariant 2/3), the active discount as a negative
line (invariant 4), plus any ad-hoc charges (electricity, penalty, …) added
manually while the invoice is a draft. Bulk generation covers a whole
property. Module 09 (Payments) will drive paid/partially-paid status.

## Data model (as-built)

```
Table: invoices                                 (RLS enforced, app: apps.billing)
  id                uuid PK
  tenant_id         uuid              (RLS)
  resident          FK -> residents.Resident (PROTECT)
  period_start / period_end   date
  billing_mode      monthly | weekly | daily   (snapshot from admission)
  issue_date        date, null        (set when issued)
  due_date          date
  status            draft | issued | partially_paid | paid   (default draft)
                    -- Module 08 sets only draft/issued; paid/partially_paid
                    -- are Module 09's. "Overdue" is DERIVED (is_overdue), never stored.
  notes             text, blank
  created_by        FK -> users, null (SET_NULL)
  created_at / updated_at
  -- total is summed from line_items in the serializer, never stored.

Table: invoice_line_items                       (RLS enforced, app: apps.billing)
  id                uuid PK
  tenant_id         uuid              (RLS)
  invoice           FK -> invoices (CASCADE)
  line_type         accommodation | food | electricity | water | laundry |
                    addon | additional | discount | penalty
  label             varchar(255)      (free display text)
  amount            decimal(12,2)     (NEGATIVE for a discount line)
  order             smallint          (display order)
  created_at / updated_at
```
Also added this module: `admissions.addons` JSONField (default `[]`) — the
reserved field mandated by invariant 6 / PRD "Future-Proofing" so add-ons can
land later with no migration (see Module 05 spec).

## API endpoints
```
GET|POST         /api/v1/invoices/                       list / generate (one resident)   manage_invoices
GET|PATCH|DELETE /api/v1/invoices/{id}/                  detail / edit due_date+notes / delete draft   manage_invoices
POST             /api/v1/invoices/{id}/issue/            draft -> issued                  manage_invoices
POST             /api/v1/invoices/bulk-generate/         generate drafts for a property   manage_invoices
POST             /api/v1/invoices/{id}/line-items/       add an ad-hoc line (draft only)  manage_invoices
PATCH|DELETE     /api/v1/invoices/{id}/line-items/{lid}/ edit / remove a line (draft only) manage_invoices
```

## Business rules (each maps to a test)
1. Generation creates a draft invoice with an **accommodation** line whose
   amount is the resident's `allocation.contracted_rent` (invariant 2) —
   labeled "Accommodation + Food (Mode)" with food, "Accommodation (Mode)"
   without. Food is baked into contracted_rent (the with/without-food rack
   rate chosen at admission), so there is no separate food line — matching
   the PRD examples.
2. A **temporary allocation** is still billed at `contracted_rent`
   (invariant 3) — the temp room's rack rate is irrelevant (directly tested).
3. If the resident has a **discount active on `period_start`** it's added as
   its own negative line (invariant 4), computed on the accommodation amount
   charged (`contracted_rent` for a normal month). Two residents in the same
   room get their own discount lines.
4. The **first** invoice for a resident uses `admission.first_month_billing_amount`
   (+ note in the label) if set; later invoices use full `contracted_rent`.
5. `total` = sum of line items (invariant 5: Decimal throughout), summed in
   the serializer, never stored.
6. Line items are fully editable **while the invoice is a draft** (add / edit
   / remove) so management has full manual control — partial months, transfer
   splits, electricity/water/laundry/additional charges, and the late-payment
   **penalty** (a manual line — see Decisions). Modifying a non-draft invoice
   is rejected (`invoice_not_draft`).
7. `issue` moves draft → issued and stamps `issue_date`. **Overdue** is
   derived (`is_overdue` = issued & past due date), never a stored status.
8. Bulk generation creates drafts for every Active/Notice-Period resident in
   a property that has an allocation and no invoice yet for that
   `period_start` (idempotent — re-running creates 0).
9. No duplicate invoice for the same resident + `period_start`
   (`duplicate_invoice`). Only Active/Notice-Period, allocated residents can
   be invoiced.
10. Draft invoices are deletable (regenerate); issued invoices are immutable
    financial records (no edit/delete). Generation, issue, delete, and every
    line-item change are audit logged.
11. `manage_invoices` (Super Admin, Owner, Manager) gates everything;
    Receptionist/Resident get 403. Scoped to the actor's assigned properties.
12. `invoices` and `invoice_line_items` are RLS-enforced (isolation proven).

## Permissions
- `manage_invoices` (Super Admin, Owner, Manager): all endpoints, scoped to
  assigned properties for Manager.
- Receptionist and Resident: no access.

## Edge cases handled
- Prefetched `line_items` are re-fetched after a line mutation so the response
  reflects the change (no stale cache).
- A percentage discount on a partial first month is computed on the manual
  first-month amount actually charged (the accommodation line base).
- Generating for a resident who isn't allocated / not Active is rejected
  before any invoice row is created.

## Open questions / Decisions
- [DECISION 2026-07-03] **Penalty is a MANUAL line, not auto-applied.** PRD
  Module 2B/9 say the late-payment penalty is added "automatically after the
  grace period," but PRD Module 10 explicitly says "No auto-penalty for late
  payment in MVP — management handles manually." The MVP qualifier decides:
  management adds a `penalty` line item themselves (the Module 03 property
  settings are available to inform the amount). Auto-penalty (likely a Celery
  job) is post-MVP.
- [DECISION 2026-07-03] **Accommodation = `allocation.contracted_rent`, not a
  separate food line.** contracted_rent already reflects the food choice
  (with/without-food rack rate snapshotted at admission), exactly matching the
  PRD's "Accommodation + Food ₹7,000 / Total ₹7,000" example. The "Food
  Charges" component in the PRD list is vestigial for this pricing model.
- [DECISION 2026-07-03] **Transfer rent split / effective date is a manual
  adjustment.** PRD Module 2B literally says "Management manually adjusts the
  invoice" for an immediate transfer. Rather than build a proration engine
  around `rent_effective_date`, line items are fully editable while draft, so
  management edits the accommodation amount for a transition month. Module 06's
  `rent_effective_date` is informational for that manual step.
- [DECISION 2026-07-03] **"Overdue" is derived, not stored.** Storing it would
  need a scheduled job; instead `is_overdue` is computed (issued & past due).
  Stored `status` covers draft/issued (this module) and paid/partially_paid
  (Module 09).
- [DECISION 2026-07-03] `Invoice`/`InvoiceLineItem` live in `apps.billing`
  alongside `Discount`. `total` is computed (not stored) to avoid drift,
  consistent with the Module 02 counts decision.
- [DECISION 2026-07-03] Reserved `addons` JSONField added to `Admission` (not
  Invoice) per the PRD's explicit "the `resident_admission` record should have
  a reserved `addons` JSON field." The invoice engine already iterates a
  line-item list, so a future add-on simply becomes another line item — zero
  engine change (invariant 6 satisfied on both counts).
- [DECISION 2026-07-03] No formal human-readable invoice number in MVP —
  invoices are referenced by UUID. A per-tenant sequential number can be added
  with Module 09 receipts if needed (deferred to avoid concurrency/sequence
  complexity now).
- [OPEN] Discount reports (PRD Module 8: total discount given this month,
  breakdown by reason) now have the data (discount lines on invoices) but the
  report endpoints are deferred to dashboards / Module 17.
- [OPEN] Weekly/daily invoice-on-checkout automation (PRD) isn't built; the
  billing_mode field and manual generation support it, but the check-out
  trigger is Module 10's concern.

## Changelog
- 2026-06-xx  Created stub.
- 2026-07-03  Built: `Invoice` + `InvoiceLineItem` line-item engine (RLS),
  generation (accommodation + discount + first-month), bulk generation, issue
  action, draft-only line-item add/edit/remove, derived overdue, audit logging;
  added reserved `admissions.addons` field. 25 invoice tests (+ discount tests
  from Module 07). Spec written to as-built.
