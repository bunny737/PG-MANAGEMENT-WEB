# Module: Deposits / Advance / Vacating / Absconded

> Keep this file in sync with the code AT ALL TIMES.
> If the code and this file disagree, this file is wrong — fix it in the same commit.

**Status:** Done
**Phase:** 2
**PRD reference:** Module 11 (Security Deposit & Advance Management)
**Depends on:** 08
**Blocks:** none

## Purpose
Owner/Manager run the two ways a resident's stay ends: a **normal vacate**
(notice given → 1-month notice period → move-out settlement with a
maintenance deduction and advance refund) or being marked **absconded**
(left without notice — bed freed immediately, advance forfeited against
outstanding dues). An absconded (or notice-period) resident can then be
**blacklisted** — a tenant-wide flag, never automatic, that warns staff at
any property under the tenant if the same phone/Aadhaar tries to re-register.

## Data model (as-built)

```
Table: vacates                                  (RLS enforced, app: apps.residents)
  id                    uuid PK
  tenant_id             uuid              (RLS)
  resident              OneToOne -> residents.Resident (PROTECT)
  notice_given_date     date
  expected_vacate_date  date              (notice_given_date + 1 month, auto-calculated)
  actual_vacate_date    date, null        (set when settlement is finalized)
  maintenance_deduction        decimal(12,2), null
  maintenance_deduction_note   text, blank
  refund_date           date, null
  refund_mode           upi | cash | bank_transfer, blank
  refund_note           text, blank
  settled_by            FK -> users, null (SET_NULL)
  created_at / updated_at
  -- refund_amount = advance_amount - maintenance_deduction, computed, never stored.

Table: absconded_records                        (RLS enforced, app: apps.residents)
  id                    uuid PK
  tenant_id             uuid              (RLS)
  resident              OneToOne -> residents.Resident (PROTECT)
  absconded_date        date
  last_seen_date        date, null
  absconded_note        text, blank
  advance_forfeited     boolean, default True
  advance_applied_to_dues  decimal(12,2)  (snapshotted at marking time)
  remaining_dues           decimal(12,2)  (snapshotted at marking time)
  dues_recovery_status  outstanding | partially_recovered | written_off (default outstanding)
  dues_written_off_by   FK -> users, null (SET_NULL)
  dues_written_off_note text, blank
  marked_by             FK -> users, null (SET_NULL)
  created_at / updated_at

Table: blacklist_entries                        (RLS enforced, app: apps.residents)
  id                    uuid PK
  tenant_id             uuid              (RLS, tenant-wide — NOT property-scoped)
  resident              OneToOne -> residents.Resident (PROTECT)
  phone                 varchar(15)       (snapshotted from resident)
  aadhaar_number        varchar(20), blank (snapshotted from resident)
  reason                text, blank
  confirmed_by          FK -> users, null (SET_NULL)
  created_at / updated_at
```
Also added this module — two fields on `residents.Admission` (Module 05),
completing the PRD's advance trio alongside the already-existing
`advance_amount`:
```
  advance_collected_date  date, null
  advance_mode             upi | cash | bank_transfer, blank
```

## API endpoints
```
GET|POST   /api/v1/vacates/                      list / give notice (Active -> Notice Period)   manage_deposits
GET        /api/v1/vacates/{id}/                 retrieve
POST       /api/v1/vacates/{id}/finalize/        move-out settlement (Notice Period -> Vacated) manage_deposits

GET|POST   /api/v1/absconded-records/            list / mark absconded (Active -> Absconded)     manage_deposits
GET        /api/v1/absconded-records/{id}/       retrieve
POST       /api/v1/absconded-records/{id}/write-off/  write off remaining dues (mandatory note)  manage_deposits

GET|POST   /api/v1/blacklist-entries/            list (tenant-wide) / confirm blacklist          manage_deposits
GET        /api/v1/blacklist-entries/{id}/       retrieve
GET        /api/v1/blacklist-entries/check/      ?phone=&aadhaar_number= — warning lookup        manage_deposits
```
No `PATCH`/`DELETE` anywhere — these are append-only settlement/history
records, consistent with Module 08/09's "financial record is immutable"
discipline; corrections happen via the dedicated actions (`finalize`,
`write-off`) or a fresh record, not by editing history in place.

## Business rules (each maps to a test)
1. **Give notice** (`POST /vacates/`) requires the resident to currently be
   `Active` (`resident_not_active`); creates the `Vacate` row and moves the
   resident to `Notice Period`. `expected_vacate_date` is auto-calculated as
   `notice_given_date + 1 month` (PRD "Standard notice period: 1 month"),
   clamped to the last valid day of a shorter month (31 Jan → 28/29 Feb).
2. A resident can only have **one** `Vacate` row (`vacate_already_exists`).
3. **Finalize** (`POST /vacates/{id}/finalize/`) is the move-out settlement:
   records `actual_vacate_date`, `maintenance_deduction` (management's
   entry, no fixed formula), frees the bed **immediately** on finalize
   (invariant: bed status flip cascades to Module 02's room-status sync),
   and moves the resident to `Vacated`. Rejected once already settled
   (`already_settled`).
4. `maintenance_deduction` cannot be negative or exceed the admission's
   `advance_amount` (`deduction_exceeds_advance`) — "management can choose
   to refund the full advance" (zero deduction) is the floor.
5. `refund_amount` = `advance_amount - maintenance_deduction`, computed on
   the fly (invariant 5: Decimal, never stored, can't drift).
6. **Mark absconded** (`POST /absconded-records/`) requires `Active`
   (`resident_not_active`); frees the bed **immediately** (no notice
   period, unlike a normal vacate); computes outstanding dues as the sum of
   `balance_due` across the resident's `issued`/`partially_paid` invoices
   (Module 08/09); the advance is always forfeited and applied against
   those dues up to the advance amount
   (`advance_applied_to_dues = min(advance_amount, outstanding_dues)`);
   any remainder is `remaining_dues`, recorded `outstanding`. Moves the
   resident to `Absconded`.
7. **Write off** (`POST /absconded-records/{id}/write-off/`) requires a
   non-blank `note` (`note_required` — PRD "owner can write off with
   mandatory note") and sets `dues_recovery_status` to `written_off`,
   stamping `dues_written_off_by`. Rejected if already written off
   (`already_written_off`).
8. **Confirm blacklist** (`POST /blacklist-entries/`) requires the resident
   be transition-eligible to `Blacklisted` per Module 04's exact graph
   (from `Absconded` or `Notice Period` — `invalid_status_transition`
   otherwise); snapshots `phone`/`aadhaar_number` onto the entry and moves
   the resident to `Blacklisted`. Never automatic — always an explicit
   action (PRD: "Owner must explicitly confirm blacklisting").
9. **Blacklist check** (`GET /blacklist-entries/check/?phone=&aadhaar_number=`)
   is a **tenant-wide**, **non-blocking** lookup (PRD: "the system shows a
   warning" — it does not stop registration) used before creating a new
   Resident. Deliberately not property-scoped, so a Manager assigned only to
   Property B is still warned about a blacklist entry created from Property A
   (PRD: "Blacklist flag is visible across all properties of the tenant").
10. Give-notice/mark-absconded/finalize/write-off/confirm-blacklist are all
    audit logged (the specific action plus, where the resident's `status`
    changes, a paired `resident.status_changed` entry).
11. `manage_deposits` (Super Admin, Owner, Manager) gates every
    `Vacate`/`AbscondedRecord`/`BlacklistEntry` endpoint; Receptionist gets
    403. `Vacate`/`AbscondedRecord` are scoped to the actor's assigned
    properties; `BlacklistEntry` deliberately is not (see rule 9).
12. `vacates`, `absconded_records`, `blacklist_entries` are RLS-enforced
    (isolation proven).

## Permissions
- `manage_deposits` (Super Admin, Owner, Manager): all endpoints in this
  module, `Vacate`/`AbscondedRecord` scoped to assigned properties for
  Manager, `BlacklistEntry` tenant-wide for all three roles.
- Receptionist and Resident: no access.

## Edge cases handled
- Deleting/editing history is not offered anywhere in this module — a
  wrong `finalize` or `write-off` is corrected by support/data-fix, not a
  user-facing endpoint, matching how an issued Invoice/Payment is immutable.
- `outstanding_dues_for()` only sums `issued`/`partially_paid` invoices —
  a `draft` invoice was never a financial obligation and is excluded.
- `advance_applied_to_dues`/`remaining_dues` are snapshotted at the moment
  of marking absconded rather than recomputed later, so a subsequent
  (unusual) payment against an absconded resident's invoice doesn't
  retroactively change what was already recorded as forfeited/outstanding.

## Open questions / Decisions
- [DECISION 2026-07-04] **App placement:** `Vacate`/`AbscondedRecord`/
  `BlacklistEntry` live in `apps.residents` (same app as `Resident`/
  `Admission`/`Allocation`/`Transfer`), not a new `apps.deposits` app —
  same rationale as Module 05/08's placement decisions: these are
  resident-lifecycle events, and the original bootstrap only scaffolded
  domain-grouped apps. The one financial calculation this module needs
  (`outstanding_dues_for`, summing `Invoice.balance_due`) reaches into
  `apps.billing` via a deferred (function-body) import to avoid a
  module-level circular import, since `apps.billing` already imports
  `apps.residents` at load time.
- [DECISION 2026-07-04] **Permission: `manage_deposits` covers everything
  in this module, including blacklist confirmation and dues write-off —
  Manager included.** The Absconded-workflow prose says "Owner must
  explicitly confirm blacklisting" and "owner can write off... with
  mandatory note," which read as Owner-only. But the PRD's authoritative
  §6 Permission Matrix lists only `manage_deposits` (Super Admin/Owner/
  Manager, no Receptionist) for this whole module, and the Role Overview
  section explicitly lists "Security deposit and advance management" and
  "Vacating workflow and deduction entry" among Manager's day-to-day
  capabilities. Resolved the same way Module 03 resolved an analogous
  prose/matrix conflict: the matrix wins. "Owner" in the workflow prose is
  read as "the owner or whoever they've delegated operations to (Manager)."
- [DECISION 2026-07-04] **The existing generic `PATCH /residents/{id}/status/`
  (Module 04) is left untouched and still technically permits a bare
  `Active → Absconded` or `Notice Period → Blacklisted` flip with none of
  this module's side effects** (no bed release, no `AbscondedRecord`/
  `BlacklistEntry`, no advance/dues calculation). This is the same accepted
  gap already documented in Module 05 (Reserved → Active is technically
  reachable the same way, bypassing Check-In). The dedicated endpoints in
  this module are the intended production path; fixing the generic
  endpoint to block these transitions would require changing Module 04's
  already-shipped, tested code, which is out of scope here. Revisit if the
  product owner wants the generic endpoint locked down.
- [DECISION 2026-07-04] **Overpayment/advance edge case: no "credit"
  concept.** `refund_amount` and `advance_applied_to_dues` are both bounded
  by `advance_amount` (deduction validated `<= advance_amount`; dues
  application uses `min(advance, outstanding)`), so neither can go
  negative or exceed the advance actually held — consistent with Module
  09's decision to reject overpayment rather than model credit.
- [OPEN] **"Partially Recovered" dues status has no explicit trigger.** The
  PRD lists `dues_recovery_status` as Outstanding/Partially Recovered/
  Written Off, but only describes the Outstanding→Written Off transition
  ("owner can write off"). No workflow describes what marks dues
  "Partially Recovered" (e.g., a later manual payment against the
  resident). Only `write-off` (→ Written Off) is implemented; revisit if
  the product owner wants a recovery-tracking action.
- [OPEN] Dashboard indicators (PRD: dedicated "Absconded" section, `⚠
  Absconded — ₹X dues unrecovered` badge, blacklist re-registration warning
  wired into the resident-creation UI) are frontend/Module 17 concerns —
  this module only provides the data (`/absconded-records/`,
  `/blacklist-entries/check/`).

## Changelog
- 2026-06-xx  Created stub.
- 2026-07-04  Built: `Vacate` (give notice + finalize settlement),
  `AbscondedRecord` (mark absconded + dues write-off), `BlacklistEntry`
  (confirm + tenant-wide check) — all RLS-enforced in `apps.residents`.
  Added `advance_collected_date`/`advance_mode` to `Admission`. Bed release
  cascades to Module 02's room-status sync on both finalize and mark-
  absconded. 29 new tests (notice/finalize lifecycle, deduction/refund
  math, absconded dues calculation, write-off, blacklist confirm + tenant-
  wide check, permission scoping, RLS isolation); full suite (257) green.
  Spec written to as-built.
