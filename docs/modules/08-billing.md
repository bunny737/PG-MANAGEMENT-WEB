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
  created_by        FK -> users, null (SET_NULL; null = drafted by automatic billing)
  auto_generated    bool (default false)         -- drafted by the daily sweep
  review_reasons    varchar[] (default [])       -- non-empty = owner must confirm; never auto-issued
                    weekly | first_partial | transition | late | vacating |
                    no_prior_invoice | ineligible | rule_changed
  due_date_policy   from_period_start | from_issue_date | manual  (default from_period_start)
  auto_issue_on     date, null                   -- day the sweep issues it (only while no reasons)
  auto_issue_held   bool (default false)         -- the owner's hold
  created_at / updated_at
  -- total is summed from line_items in the serializer, never stored.

Table: auto_billing_cycles                      (RLS enforced, app: apps.billing)
  id, tenant_id, resident FK (CASCADE), period_start, period_end,
  outcome  created | skipped_overlap, invoice FK null (SET_NULL),
  created_on date (the sweep's effective date)
  UNIQUE (resident, period_start)
  -- "automation already handled this cycle": a deleted draft is never
  -- recreated and still counts as covered when the next cycle is planned.

Table: auto_billing_notices                     (RLS enforced, app: apps.billing)
  id, tenant_id, resident FK (CASCADE), kind (coverage_gap), key_date
  UNIQUE (resident, kind, key_date)              -- a warning sent once, not daily

Table: auto_billing_summaries                   (RLS enforced, app: apps.billing)
  id, tenant_id, property FK (CASCADE), on_date,
  created / scheduled / needs_confirmation (counts), gaps (resident names),
  delivered_to uuid[] (users reached), attempts, completed
  UNIQUE (property, on_date)                     -- the owner summary owed, kept until delivered

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
POST             /api/v1/invoices/bulk-issue/            {ids:[...]} issue many; per-id results   manage_invoices
POST             /api/v1/invoices/{id}/hold-auto-issue/  owner hold on a scheduled auto draft     manage_invoices
POST             /api/v1/invoices/{id}/resume-auto-issue/ lift the hold (next day at the earliest) manage_invoices
POST             /api/v1/invoices/bulk-generate/         generate drafts for a property   manage_invoices
POST             /api/v1/invoices/{id}/line-items/       add an ad-hoc line (draft only)  manage_invoices
PATCH|DELETE     /api/v1/invoices/{id}/line-items/{lid}/ edit / remove a line (draft only) manage_invoices
```
List filters (2026-10-16, UX roadmap D3): `?property=&resident=&billing_mode=
&period=YYYY-MM&search=&status=` where `status` is a comma list of stored
statuses (draft, issued, partially_paid, paid) or one of the derived aliases
`outstanding` (issued/partially-paid with balance > 0 — the same definition
as `/invoices/outstanding/` and the analytics `outstanding_total`) or
`overdue` (outstanding past its due date). Unknown values → 400
`INVALID_STATUS`; `period` must be `YYYY-MM`. Rows now also carry
`resident_name, property, property_name, room_number, bed_number` and
`capped_allocated` = min(amount_paid, max(total, 0)) — the per-invoice
contribution to analytics `period_collected`. Money figures for filters and
analytics come from `apps/billing/selectors.py` (DB annotations), so a list
and the summary that drills into it share one definition.

`?review=needs_confirmation|scheduled|held` (2026-10-28) narrows to automatic
drafts: needing confirmation (any review reason), scheduled for auto-issue, or
on hold. Unknown values → 400 `invalid_review`. Invoice rows also carry
`auto_generated, review_reasons, due_date_policy, auto_issue_on,
auto_issue_held, can_auto_issue`. Manual generate / bulk-generate now reject a
period overlapping any of the resident's invoices (`overlapping_invoice`; bulk
skips it and reports `skipped_overlapping`). PATCHing `due_date` on a draft sets
`due_date_policy=manual` (kept as typed, never recomputed).

## Automatic billing (owner decision 2026-10-28)
`apps/billing/autobilling.py`, run daily at 06:00 IST by the beat task
`billing.auto_billing` (seeded by migration 0008, retimable in Django admin;
ops fallback `manage.py run_auto_billing [--date YYYY-MM-DD]`). Per property
with `PropertySettings.auto_billing_enabled` (default **on**, existing
properties included):

1. **Issue** every non-held auto draft whose `auto_issue_on` is today or
   yesterday (one missed run tolerated). Rechecked under the locks: property
   still enabled, resident Active/Notice with an allocation, and no open notice
   ending before `period_end`. A failed check adds `vacating` / `ineligible`
   (or `late` when the schedule is ≥2 days old) and clears the schedule instead.
   Issued after `period_start` ⇒ due = issue date + grace.
2. **Draft** each Active/Notice, allocated, non-daily resident's next cycle,
   at most one per resident per day (`AutoBillingCycle.created_on`), and only
   when it starts no later than tomorrow.
3. **Notify** the Owner(s) and the property's staff with `manage_invoices`
   (`invoice_drafts_ready`, email + push) when it drafted or flagged anything,
   or found a new coverage gap. Each draft, flag and gap notice adds its line
   to the day's `AutoBillingSummary` **in its own transaction**, so the owner
   is owed a summary exactly when the change commits (a failed summary write
   rolls the draft/flag back for the next run; a crash can't leave news
   without a summary). The summary row is locked last in the billing lock
   order. The sweep then only delivers. A recipient
   counts as reached once any channel sent it (or none could — no template /
   address); a failed send or exception leaves them pending. Pending summaries
   up to 2 days old are retried by every sweep and every 30 minutes by
   `billing.retry_auto_billing_summaries` (migration 0009), so a failure is
   normally resent before the drafts auto-issue, and only to recipients not
   yet reached.

**Cycle selection — continue from the last covered day.** `next_start` = the
day after the latest `period_end` of the resident's invoices and
`AutoBillingCycle` markers (or `joining_date` if neither). If `next_start` is a
billing day ⇒ a full cycle up to the next billing day − 1; else a **partial**
(`first_partial` when it is the joining date, otherwise `transition`) —
decided by the schedule boundaries, never by the price (a partial capped at a
full cycle's rent, e.g. Jan 16–Feb 14 with day 15, is still a partial). Billing
days: the resident's joining day each month, clamped to month end (31st ⇒
30 Apr, 28/29 Feb), or the property's fixed day (1–28); **weekly** residents
every 7 days from joining whatever the rule; **daily** residents never.
Rollout: a never-billed resident who joined before the current cycle starts at
the current cycle (`no_prior_invoice`) — earlier months are not backfilled.

**Amounts.** Base = `admission.first_month_billing_amount` only when the period
starts on the joining date; else contracted rent × calendar fraction. The
fraction is exactly 1 for a full cycle; a monthly partial sums each calendar
month's `days / days_in_month` (Jan 20–Feb 14 = 12/31 + 14/28), capped at 1;
a weekly partial is `days / 7`. Rounded half-up to paise once. Discount: a %
discount on the base charged; a fixed discount × the same calendar fraction;
none when contracted rent is 0. Due date at draft = `period_start` + grace days.

**Review reasons (never auto-issued while any is present):** `weekly`,
`first_partial`, `transition`, `late` (drafted on/after its start ⇒ due from
issue date), `vacating` (open notice ends before `period_end`),
`no_prior_invoice`, `ineligible`, `rule_changed` (the property's automatic
billing switch / rule / day changed while it was scheduled — the settings PATCH
flags them in the same transaction). Several can apply at once; confirming =
issuing (manually or via `bulk-issue`).

**Hold / resume.** Only for auto drafts with no review reasons
(`not_auto_issuable` otherwise). Held drafts are skipped by both issuing and
the stale check. Resume schedules `max(period_start, tomorrow)` — a
calendar-day boundary, not 24 hours — and if that is after `period_start` the
due date is recomputed from the issue date (unless `manual`).

**Locking — one global order:** `PropertySettings` → `Resident`
(`residents.services.lock_resident`) → `Vacate` → `Invoice` → `Admission`.
Auto generation: Settings → Resident. Every issue (auto, manual, bulk):
Settings → Resident → Invoice → Admission, grace days read under the Settings
lock. Settings PATCH: Settings → Invoice. Draft edits / delete / line items /
hold / resume: Invoice row lock + draft recheck. `generate_invoice` itself
takes the Resident lock and checks overlap inside it, so every generation path
(single, bulk, auto) serializes per resident.

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
   (`duplicate_invoice`), and (since 2026-10-28) no invoice whose period
   overlaps another of the resident's invoices (`overlapping_invoice`),
   checked under the resident row lock on every generation path. Only
   Active/Notice-Period, allocated residents can be invoiced.
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
- [DECISION 2026-07-04] Module 14 hooked the "Invoice generated notification
  to resident" (PRD Module 18) onto the `issue` action, not `create` — a
  draft has no obligation for the resident to be told about.
- [DECISION 2026-09-10] **`unique_invoice_per_resident_period` DB constraint
  added** (`Invoice(resident, period_start)`). The generate / bulk-generate
  `.exists()` pre-checks race — two concurrent "generate" requests would bill
  the resident twice. `generate_invoice` now creates the row in a savepoint
  and maps the resulting `IntegrityError` to the existing `duplicate_invoice`
  validation error; `bulk_generate` swallows it and skips. Mirrors
  `SubscriptionInvoice.unique_invoice_per_cycle` (Module 13).
- [DECISION 2026-10-28] **Automatic invoicing** (owner). Billing day =
  per-property setting, default the resident's admission date each month,
  alternative a fixed day 1–28. Draft the day before, auto-issue on the day;
  due = billing date + `penalty_grace_days`. Weekly residents always need
  confirmation; daily residents are never auto-billed. On by default for all
  properties, existing ones included, never overlapping an existing invoice.
- [DECISION 2026-10-28] (owner) A draft created on/after its start date is
  `late`: needs confirmation, due = issue date + grace (set when issued).
- [DECISION 2026-10-28] (owner) Proration splits per calendar month
  (Jan 20–Feb 14 = rent × 12/31 + rent × 14/28). Capped at one full cycle:
  a partial never costs more than a full month (engineering call — the
  per-month sum can exceed 1, e.g. Jan 16–Feb 14).
- [DECISION 2026-10-28] (owner) On a partial, a % discount applies to the rent
  charged and a fixed ₹ discount is prorated. The ratio is the calendar
  fraction, not base ÷ rent, so a manual first-month amount isn't discounted
  twice; zero contracted rent ⇒ no discount line.
- [DECISION 2026-10-28] (owner) Changing the rule / day or switching
  automation off moves scheduled drafts to review (`rule_changed`); billing
  continues from the last covered day, bridging to the new billing day with a
  prorated `transition` draft.
- [DECISION 2026-10-28] **No overlapping invoices is now a platform
  invariant, manual generation included** (was: identical `period_start`
  only). Partial months and transfer splits are line edits, never a second
  overlapping invoice, so nothing legitimate needs an overlap.
- [DECISION 2026-10-28] **Automation bills forward only.** It continues after
  the latest recorded period; gaps before it (incl. before a future-dated
  manual invoice) are left to the owner. The one gap it detects — today
  uncovered while a later period is billed — is warned about once
  (`AutoBillingNotice`).
- [DECISION 2026-10-28] `first_month_billing_amount` applies to an automatic
  draft only when its period starts on the joining date, never just because
  it is the first invoice in the database (a rollout must not re-apply an old
  admission concession). The manual path keeps its original behaviour.
- [DECISION 2026-10-28] A scheduled draft still auto-issues one day late
  (missed sweep), due from the issue date; older ⇒ `late` for review. Held
  drafts are exempt from both, so Resume always stays available.
- [DECISION 2026-10-28] A Notice-Period resident's draft is flagged
  `vacating` only when the open notice ends before `period_end`; no draft at
  all for a cycle starting after the expected vacate date.
- [DECISION 2026-10-28] A due date typed by the owner on a draft
  (`due_date_policy=manual`) is never recomputed by automation.
- [DECISION 2026-10-28] `issue_date` uses the product-timezone date
  (`core.periods.local_today`, or the sweep's effective date), not the
  container clock (`date.today()`, a day behind before 05:30 IST).
- [DECISION 2026-10-28] Every system (actor-less) audit row passes
  `tenant_id` explicitly — `audit_log.record` only infers it from the actor.

## Changelog
- 2026-06-xx  Created stub.
- 2026-07-03  Built: `Invoice` + `InvoiceLineItem` line-item engine (RLS),
  generation (accommodation + discount + first-month), bulk generation, issue
  action, draft-only line-item add/edit/remove, derived overdue, audit logging;
  added reserved `admissions.addons` field. 25 invoice tests (+ discount tests
  from Module 07). Spec written to as-built.
- 2026-07-04  Module 14 added an email-notification dispatch (via
  `transaction.on_commit` + Celery) to the `issue` action — no other change
  to invoice issuance itself.
- 2026-10-04  `issue` now applies the resident's advance
  (`apply_advance_to_first_invoice`): when the FIRST issued invoice for a
  resident is issued, a Payment of `min(advance_amount, balance_due)` is
  recorded (mode/date from the admission, reference "Advance collected at
  admission") via `record_payment`, so the invoice becomes paid/partially_paid
  and a receipt email is sent. `Admission.advance_applied_amount` records the
  amount; any surplus stays refundable at vacate (Module 10). Later invoices
  get nothing. Decision: only the first issued invoice qualifies; an advance of
  0 does nothing.
- 2026-10-04  Review fixes for the advance application: it now row-locks the
  Admission and re-checks `advance_applied_amount` so two concurrent `issue`
  calls can't both apply it, and `advance_applied_amount` accumulates instead
  of being overwritten. Deleting the advance Payment (identified by
  `ADVANCE_PAYMENT_REFERENCE`) subtracts it from `advance_applied_amount`, so
  `advance_refundable` stays correct for the vacate refund.
- 2026-10-06  Note for Module 18: `property_features.is_paid` is informational
  ("Included" vs "Extra cost") and is never read by the invoice engine. Chargeable
  add-ons still go through invoice line items / the reserved `addons` JSON (invariant 6).
- 2026-10-12  Discount/Invoice viewsets use `require_permission_by_method('view_finance', 'manage_*')`:
  `GET`/`HEAD`/`OPTIONS` (incl. `outstanding`) need `view_finance`, every write (incl. `issue`,
  `bulk-generate`, line items) needs the `manage_*` code. Role defaults are unchanged (Owner/Manager
  have both). See Module 01 `[DECISION 2026-10-12]`.
- 2026-10-16  UX roadmap D3: `InvoiceFilter` (`apps/billing/filters.py`) with
  property / period / search / status incl. derived `outstanding` and
  `overdue` aliases; `/invoices/outstanding/` now uses the same DB-side
  definition (`apps/billing/selectors.py`) and honours the list filters;
  invoice rows gained resident/property/room/bed context and
  `capped_allocated`; `is_overdue` uses the product-timezone date
  (`core.periods.local_today`) instead of the container clock. Tests:
  `billing/tests/test_list_filters.py`.
- 2026-10-28  Automatic invoicing (owner request): `apps/billing/autobilling.py`
  daily sweep + `billing.auto_billing` beat task + `run_auto_billing` command;
  `Invoice` review / schedule fields; `AutoBillingCycle` and `AutoBillingNotice`
  (RLS); `issue_invoice` service (extracted from the view, global lock order,
  eligibility recheck); `hold-auto-issue` / `resume-auto-issue` / `bulk-issue`
  endpoints; `?review=` filter; overlap rejection on every generation path;
  `invoice_drafts_ready` notification (Module 14). Property settings fields in
  Module 03. Tests: `test_auto_billing_math.py`, `test_auto_billing.py`,
  `test_auto_billing_concurrency.py` (threaded lock-order races). Owner UI:
  settings section, Needs review / Auto-issue scheduled list filters with
  "Issue selected", detail banner with Hold / Resume.
- 2026-10-28  Review fixes: (1) partial status comes from the schedule, not
  the capped price — a Jan 16–Feb 14 period priced at one full cycle was
  auto-issuing without confirmation; (2) owner summaries are persisted
  (`AutoBillingSummary`, RLS) and retried per recipient by each sweep and a
  30-minute beat task until delivered, instead of being lost on a failed
  send; (3) the 06:00 crontab seed includes the timezone in its lookup, so an
  existing 06:00 UTC schedule is never reused.
- 2026-10-28  Review fix: the summary line is written in the same transaction
  as the draft / flag / gap notice it reports (`note_in_summary`), closing the
  window where a draft committed but its summary failed to save or the worker
  stopped in between — the owner would never have been told.
- 2026-10-30  Module 24 (food holidays): new `food_holiday` line type (negative and system-owned: it can't
  be added, retyped or PATCHed by hand, and deleting it waives the credit). `generate_invoice` now takes
  the Settings lock before the Resident lock and, after the discount line, creates and allocates
  food-holiday credits (optional `on_date`). Invoice delete releases credits first, and draft line
  add/edit/delete rebalances them. `_locked_draft` takes the Settings lock first. Lock order:
  Settings → FoodHoliday → Resident → Vacate → Invoice → FoodHolidayCredit → Admission. See
  24-notices-holidays.md.
- 2026-10-30  `generate_invoice` uses the resident row it locks (not the caller's copy) and re-checks
  billability under the lock. `ResidentNotBillable` (`resident_not_billable` / `resident_not_allocated`, 400)
  is raised when the resident vacated, absconded or lost their bed while the request waited; bulk
  generation skips such residents.
