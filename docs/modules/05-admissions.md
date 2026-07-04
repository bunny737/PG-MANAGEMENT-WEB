# Module: Admissions

> Keep this file in sync with the code AT ALL TIMES.
> If the code and this file disagree, this file is wrong — fix it in the same commit.

**Status:** Done
**Phase:** 1
**PRD reference:** Module 6 (Admission Management)
**Depends on:** 04
**Blocks:** 06

## Purpose
Owner/Manager perform Check-In: pick a bed for a Reserved resident, record
the deal terms (billing mode, food preference, advance), and the system
snapshots the contracted rent, occupies the bed, and activates the
resident — all in one action. This module owns the historical admission
record; the ongoing bed-assignment/transfer tracking (temporary
allocation, transfers) is Module 06.

## Data model (as-built)

```
Table: admissions                               (RLS enforced, app: apps.residents)
  id                    uuid PK
  tenant_id             uuid              (RLS)
  resident              OneToOne -> residents.Resident (PROTECT — one admission per resident, ever)
  bed                   FK -> properties.Bed (PROTECT)

  joining_date          date
  billing_mode          monthly | weekly | daily
  expected_stay_duration varchar(50), blank   (free text, e.g. "6 months")

  # Snapshotted from bed/room at admission time (invariant 2/3) — never
  # recomputed even if the room's rack rates or category change later.
  contracted_sharing_type  1 | 2 | 3 | 4
  contracted_room_category ac | non_ac
  food_preference           with_food | without_food
  contracted_rent            decimal(12,2)

  advance_amount              decimal(12,2), default 0
  advance_collected_date      date, null            (added by Module 10)
  advance_mode                upi | cash | bank_transfer, blank   (added by Module 10)
  first_month_billing_amount  decimal(12,2), null   (manual partial-month override)
  first_month_billing_note    text, blank
  addons                      jsonb, default []     (reserved; added by Module 08)

  recorded_by           FK -> users, null (SET_NULL)
  created_at / updated_at
```

## API endpoints
```
GET|POST   /api/v1/admissions/          list/create (= Check-In)   manage_admissions
GET        /api/v1/admissions/{id}/     retrieve                   manage_admissions
```
No PATCH/DELETE — an admission is immutable once created (405 on both).

## Business rules (each maps to a test)
1. Creating an Admission performs the full Check-In sequence in one
   request: (a) validates the resident is `Reserved` (reuses
   `Resident.can_transition_to(ACTIVE)` from Module 04's exact transition
   graph — also blocks double-admission, since an already-`Active`
   resident fails the same check), (b) validates the bed belongs to the
   resident's property, (c) validates the bed is `Available`, (d)
   snapshots `contracted_sharing_type`/`contracted_room_category`/
   `contracted_rent` from the bed/room (rent via `Bed.rack_rate()`, which
   already honours per-bed overrides from Module 02), (e) flips the bed to
   `Occupied` (this also syncs the room's status per Module 02), (f)
   flips the resident to `Active`, and (g) creates the resident's initial
   `Allocation` (added by Module 06 — `services.create_initial_allocation`).
2. `contracted_rent` is set once at creation and never recomputed — later
   changes to the room's rack rates don't touch existing admissions
   (invariant 2/3, directly tested).
3. `manage_admissions` (Super Admin, Owner, Manager) gates every action;
   Receptionist gets 403 on both read and write (PRD: front-desk has no
   billing/allocation access).
4. Manager/Receptionist scoping reuses
   `apps.properties.services.visible_property_ids` via the bed's property
   — a Manager can only admit into / view admissions for properties
   they're assigned to.
5. Both `admission.created` and the resulting `resident.status_changed`
   are audit logged (before/after on the resident's status).
6. `admissions` is RLS-enforced; isolation proven the same way as the
   other Module 04/02 tables.

## Permissions
- `manage_admissions` (Super Admin, Owner, Manager): list, retrieve, create.
- Receptionist and Resident: no access.

## Edge cases handled
- Admitting into a bed from a different property than the resident's own
  property is rejected (`bed_property_mismatch`), even if the actor can
  see both properties.
- Admitting into an already-`Occupied` bed is rejected
  (`bed_not_available`) — no double-booking.
- A resident who is `Inquiry` (never reserved) cannot be admitted;
  neither can one who's already `Active`/`Vacated`/etc. — same
  `resident_not_ready_for_checkin` error for both, since both fail the
  same transition-graph check.

## Open questions / Decisions
- [DECISION 2026-07-03] **App placement:** `Admission` lives in
  `apps.residents` (same app as Module 04's `Resident`), not a new
  `apps.admissions` app. The original bootstrap only scaffolded 9
  domain-grouped apps (not one per PRD module — e.g. `apps.billing` will
  cover Modules 08/09/10, `apps.operations` will cover 11/12), and
  Admission is fundamentally a resident-lifecycle event (1:1 with
  Resident), so it extends that app rather than introducing a new one.
- [DECISION 2026-07-03] **Module 05/06 boundary:** the PRD's "Allocation
  Record Fields" (Module 7) include `contracted_room_type`,
  `contracted_room_category`, `contracted_rent`, `allocated_bed` — which
  overlaps with what Admission already snapshots. To avoid Module 05
  depending on a Module 06 model that doesn't exist yet (05 must be built
  before 06), Admission owns the *initial* bed selection and contracted-
  terms snapshot directly (`bed` FK + snapshot fields). Module 06 will
  introduce its own `Allocation`/`Transfer` models for the fields that
  actually change over time (`is_temporary`, `actual_room_type`,
  `temporary_since`, transfer history), reading Admission's snapshot as
  the starting point rather than duplicating it from scratch.
- [DECISION 2026-07-03] **Reservation stage has no dedicated model.** The
  PRD workflow shows Inquiry → Property Visit → Reservation → Admission →
  Check-In, but "Reservation" isn't a numbered PRD module and defines no
  fields of its own beyond "bed held, advance collected." Module 04's
  existing generic status endpoint already covers the `Inquiry → Reserved`
  transition; this module's Admission record captures the advance amount
  and contracted terms and performs `Reserved → Active` (Check-In) in one
  action, rather than inventing an unspecified intermediate Reservation
  table.
- [DECISION 2026-07-03] `first_month_billing_amount` (Decimal, nullable)
  was added alongside `first_month_billing_note` (text). The PRD lists a
  single bullet "First Month Billing Note (partial month — amount set
  manually by management)" — the "amount set manually" phrasing implies a
  monetary value, so a Decimal field was added per invariant 5 rather
  than treating it as text-only. `null` means "bill normally"; Module 08
  is what will actually consume this field.
- [OPEN] "Documents, billing setup" (the PRD's description of the
  Admission step) isn't separately gated — Module 04 deliberately left
  document-completeness validation out of scope, and this module doesn't
  add it either. Revisit if the product owner wants Aadhaar/PAN required
  before Check-In.
- [DECISION 2026-07-04] Module 13 added a plan-limit check
  (`check_resident_limit`, checked per property per PRD §4) to
  `perform_create`, before any bed/resident mutation — a blocked check-in
  leaves the bed/resident untouched. Fail-open when no plan is configured.

## Changelog
- 2026-06-xx  Created stub.
- 2026-07-03  Built: `Admission` model (RLS, in `apps.residents`) with
  contracted-terms snapshotting, one-request Check-In (bed occupied +
  resident activated), permission scoping reusing Module 02's property-
  assignment service, audit logging, 15 tests (happy path + invariants +
  scoping + isolation). Spec written to as-built.
- 2026-07-03  Module 06 extended check-in: `perform_create` now also
  creates the resident's initial `Allocation` (step g above) inside the
  same transaction. No behaviour change to the admission record itself.
- 2026-07-03  Module 08 added the reserved `addons` JSONField (default `[]`)
  to Admission per invariant 6 / PRD "Future-Proofing" — empty in MVP, so
  future add-on services land without a schema migration.
- 2026-07-04  Module 10 added `advance_collected_date`/`advance_mode` to
  Admission, completing the PRD's advance trio alongside the existing
  `advance_amount`. No behaviour change to Check-In itself.
- 2026-07-04  Module 13 added a per-property plan-limit check to Check-In
  (see Decisions).
