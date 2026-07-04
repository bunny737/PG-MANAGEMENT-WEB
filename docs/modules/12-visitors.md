# Module: Visitors

> Keep this file in sync with the code AT ALL TIMES.
> If the code and this file disagree, this file is wrong — fix it in the same commit.

**Status:** Done
**Phase:** 3
**PRD reference:** Module 13 (Visitor Management)
**Depends on:** 04
**Blocks:** none

## Purpose
Front desk logs a visitor's entry and, later, their exit against the
resident they're visiting. Owner/Manager can additionally add an advisory
confirmation stamp on top. `manage_visitors` is the one permission in the
whole PRD matrix that includes Receptionist — this is their primary job.

## Data model (as-built)

```
Table: visitors                                 (RLS enforced, app: apps.operations)
  id                uuid PK
  tenant_id         uuid              (RLS)
  resident          FK -> residents.Resident (PROTECT)
  visitor_name      varchar(200)
  mobile_number     varchar(15)
  purpose           varchar(255)
  entry_time        datetime          (explicit input; defaults to now if omitted)
  exit_time         datetime, null    (set via the check-out action)
  logged_by         FK -> users, null (SET_NULL)   -- staff who logged entry
  checked_out_by    FK -> users, null (SET_NULL)   -- staff who logged exit
  approved_by       FK -> users, null (SET_NULL)   -- optional confirmation stamp
  created_at / updated_at
  -- is_checked_in = exit_time is None, computed, never stored.
```

## API endpoints
```
GET|POST   /api/v1/visitors/                 list / log entry              manage_visitors
GET        /api/v1/visitors/{id}/            retrieve
POST       /api/v1/visitors/{id}/check-out/  log exit ({"exit_time"?})     manage_visitors
POST       /api/v1/visitors/{id}/confirm/    optional Owner/Manager stamp  manage_visitors
```
No PATCH/DELETE — a logged entry is corrected via the dedicated actions,
not raw edits.

## Business rules (each maps to a test)
1. Logging a visitor (`POST /visitors/`) requires the resident be in a
   property the actor can see (`property_not_assigned`); `entry_time`
   defaults to now if omitted; stamps `logged_by`.
2. **Check-out** (`POST /visitors/{id}/check-out/`) sets `exit_time`
   (defaults to now if omitted) and `checked_out_by`; rejected if the
   visitor already checked out (`already_checked_out`) or if the given
   `exit_time` precedes `entry_time` (`exit_before_entry`).
3. **Confirm** (`POST /visitors/{id}/confirm/`) stamps `approved_by` from
   the request user; rejected if already confirmed (`already_confirmed`).
   It does **not** gate check-in/check-out — see Decisions.
4. `is_checked_in` (`exit_time is None`) is computed, never stored — same
   discipline as `Invoice.is_overdue`.
5. Logging, check-out, and confirm are all audit logged.
6. `manage_visitors` (Super Admin, Owner, Manager, **and Receptionist**)
   gates every endpoint — this is the only module where Receptionist has
   full access, matching the PRD §6 matrix exactly. Scoped to the actor's
   assigned properties via the resident's property. Resident (self-service
   `request_visitor`) has no access — see Decisions.
7. `visitors` is RLS-enforced (isolation proven).
8. History is filterable by `resident` (PRD "Visitor history per
   resident") and `mobile_number` (repeat-visitor lookups).

## Permissions
- `manage_visitors` (Super Admin, Owner, Manager, Receptionist): every
  endpoint, scoped to assigned properties for Manager/Receptionist.
- Resident: no access (see Decisions).

## Edge cases handled
- An Owner/Super Admin confirming or logging a visitor for any property in
  the tenant succeeds without an explicit `PropertyStaffAssignment` row,
  via `can_view_property`'s existing implicit-access short-circuit.
- Confirming before check-out (or vice versa) is fine — `confirm` and
  `check-out` are independent, order doesn't matter.

## Open questions / Decisions
- [DECISION 2026-07-04] **`request_visitor` (Resident self-service) is not
  implemented**, for the identical reason Module 11 gave for
  `raise_complaint`: Module 04 confirmed Resident profiles have no linked
  login `User` account yet, so there's no way for an actual resident to
  submit a request. Only the staff side (log/check-out/confirm) is built.
- [DECISION 2026-07-04] **`confirm` is an advisory stamp, not a hard
  approval gate.** PRD Module 13's Receptionist bullet says "Visitor
  approval (with Owner/Manager confirmation if required)" but never
  defines what makes confirmation *required*, and the "Visitor Record"
  field list (name/mobile/resident/purpose/entry/exit) has no approval
  status of its own. Rather than invent an undefined policy toggle,
  `manage_visitors` (which already includes Receptionist per the matrix)
  can independently complete the whole flow — log entry, check out, and
  optionally confirm — with `confirm` recorded as an audit-visible stamp
  layered on top, not a precondition for logging or check-out.
- [DECISION 2026-07-04] **No separate `status` field.** Unlike Complaint's
  exact linear workflow, a visitor's state is fully captured by
  `entry_time`/`exit_time`/`approved_by` — a computed `is_checked_in`
  covers "who's currently inside" without a redundant stored status that
  could drift.
- [DECISION 2026-07-04] `entry_time`/`exit_time` are explicit inputs
  (defaulting to now if omitted) rather than always auto-stamped, matching
  how other business timestamps in this codebase (`payment_date`,
  `absconded_date`) are treated as data the actor controls, not a server
  clock stamp — front desk may log an arrival slightly after the fact.
- [OPEN] QR Visitor Pass is explicitly PRD V2 — not built.

## Changelog
- 2026-06-xx  Created stub.
- 2026-07-04  Built: `Visitor` (RLS, `apps.operations`) with log/check-out/
  confirm actions, computed `is_checked_in`, resident-history filtering, and
  audit logging on every mutation. `manage_visitors` includes Receptionist
  (the only module where it does). 20 new tests (creation, check-out
  validation, confirm, scoping including the Receptionist-can-access case,
  RLS isolation); full suite (307) green. Spec written to as-built.
