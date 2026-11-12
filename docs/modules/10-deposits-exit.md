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
  resident              FK -> residents.Resident (PROTECT, related_name='vacates')
  notice_given_date     date
  expected_vacate_date  date              (notice_given_date + 1 month, auto-calculated)
  actual_vacate_date    date, null        (set when settlement is finalized)
  maintenance_deduction        decimal(12,2), null
  maintenance_deduction_note   text, blank
  refund_date           date, null
  refund_mode           upi | cash | bank_transfer, blank
  refund_note           text, blank
  cancelled_date        date, null        (set when the notice is withdrawn)
  cancellation_reason   text, blank       (mandatory on the cancel action)
  cancelled_by          FK -> users, null (SET_NULL)
  settled_by            FK -> users, null (SET_NULL)
  created_at / updated_at
  ordering: notice_given_date, created_at           -- oldest-first
  constraint unique_open_vacate_per_resident:
      UNIQUE (resident) WHERE cancelled_date IS NULL AND actual_vacate_date IS NULL
  constraint vacate_not_both_cancelled_and_settled:
      CHECK NOT (cancelled_date IS NOT NULL AND actual_vacate_date IS NOT NULL)
  -- refund_amount = security_deposit_amount - maintenance_deduction + advance_refundable,
  -- computed, never stored.
  -- is_settled / is_cancelled / is_open are computed properties.

Table: absconded_records                        (RLS enforced, app: apps.residents)
  id                    uuid PK
  tenant_id             uuid              (RLS)
  resident              OneToOne -> residents.Resident (PROTECT)
  absconded_date        date
  last_seen_date        date, null
  absconded_note        text, blank
  deposit_forfeited     boolean, default True        (renamed from advance_forfeited, 2026-10-04)
  deposit_applied_to_dues  decimal(12,2)             (renamed from advance_applied_to_dues)  (snapshotted at marking time)
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
**Several rows per resident** (changed 2026-10-07, was OneToOne): cancelling a
notice closes that row and returns the resident to Active, so a later notice is
a new row and the withdrawn one stays in history. At most one may be *open*.

`Resident` gained three accessors for reading them, all of which prefer a
`prefetched_vacates` attribute when the caller supplied one via
`vacate_prefetch()`:
- `open_vacate` — the row that is neither cancelled nor settled, or None.
- `latest_vacate` — the last row, whatever its state.
- `latest_settled_vacate` — the last **settled** row; what a Vacated resident's
  move-out date must come from, since `latest_vacate` could be a cancelled one.

Also added this module — admission advance & deposit ledger fields on
`residents.Admission` (Module 05):
```
  advance_collected_date         date, null
  advance_mode                   upi | cash | bank_transfer, blank
  first_invoice_advance_settled  boolean, default false
```

## API endpoints
```
GET|POST   /api/v1/vacates/                      list / give notice (Active -> Notice Period)   manage_deposits
GET        /api/v1/vacates/{id}/                 retrieve
GET        /api/v1/vacates/{id}/settlement-preview/  refund breakdown before finalize (below)  manage_deposits
POST       /api/v1/vacates/{id}/finalize/        move-out settlement (Notice Period -> Vacated) manage_deposits
POST       /api/v1/vacates/{id}/cancel/          withdraw notice (Notice Period -> Active)      manage_deposits

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
2. A resident can only have one **open** `Vacate` row
   (`vacate_already_exists`) — changed 2026-10-07, was one row ever. Enforced
   both in the serializer and, under the resident lock, by
   `unique_open_vacate_per_resident`.
2a. **Cancel notice** (`POST /vacates/{id}/cancel/`) withdraws the notice:
   `Notice Period -> Active`, so the resident stays on (owner request
   2026-10-07). Requires the resident to be in `Notice Period`
   (`resident_not_in_notice_period`) and the vacate to be open
   (`already_settled` / `already_cancelled`); `cancellation_reason` is
   mandatory (`reason_required`, same discipline as `write-off`).
   `cancelled_date` is caller-supplied, defaults to today, and must be
   `>= notice_given_date` (`cancelled_before_notice`) and not in the future
   (`cancelled_date_in_future`) — all re-validated in the service, not only
   the serializer.

   It deliberately touches **nothing else**: the bed was never released (only
   `finalize` does that), the `Allocation` and `contracted_rent` are untouched
   (invariant 2 — never re-derived from the room's rack rate), billing already
   treats Notice Period exactly like Active so no invoice/proration work
   applies, and the deposit/advance are only paid out at finalize. The row is
   kept as history rather than deleted, and a later notice creates a new one.
3. **Finalize** (`POST /vacates/{id}/finalize/`) is the move-out settlement:
   records `actual_vacate_date`, `maintenance_deduction` (management's
   entry, no fixed formula), frees the bed **immediately** on finalize
   (invariant: bed status flip cascades to Module 02's room-status sync),
   and moves the resident to `Vacated`. Rejected once already settled
   (`already_settled`), once cancelled (`already_cancelled`), or if the
   resident is no longer in their notice period
   (`resident_not_in_notice_period`) — the last two added 2026-10-07, without
   which settling a withdrawn notice would re-vacate an Active resident and
   free their bed.
4. `maintenance_deduction` cannot be negative or exceed the admission's
   `security_deposit_amount` (`deduction_exceeds_deposit`) — zero deduction
   (full refund) is the floor. The deduction never comes out of the advance.
5. `refund_amount` = `security_deposit_amount - maintenance_deduction +
   advance_refundable` (unapplied held advance remaining on Admission =
   `advance_amount - advance_applied_amount`), computed on
   the fly (invariant 5: Decimal, never stored, can't drift).
5a. **Settlement preview** (`GET /vacates/{id}/settlement-preview/?maintenance_deduction=`,
   owner request 2026-10-26) runs the same math as `finalize` — same
   deduction cap, same `refund_amount` formula — so the app's checkout screen
   can show the refund before a staff member confirms it, without finalize's
   formula ever drifting from the preview's. It also reports
   `outstanding_dues` (the same sum `mark_absconded` uses below), but
   **informational only**: unlike `mark_absconded`, a normal vacate never
   nets dues against the refund. Rejected once settled/cancelled, same as
   `finalize`. It is read-only — no row lock, no mutation, no audit entry
   (see Decisions).
6. **Mark absconded** (`POST /absconded-records/`) requires `Active`
   (`resident_not_active`); frees the bed **immediately** (no notice
   period, unlike a normal vacate); computes outstanding dues as the sum of
   `balance_due` across the resident's `issued`/`partially_paid` invoices
   (Module 08/09); the security deposit plus any unapplied advance is always forfeited and
   applied against those dues
   (`deposit_applied_to_dues = min(deposit + advance_refundable, outstanding_dues)`);
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
10. Give-notice/cancel-notice/mark-absconded/finalize/write-off/
    confirm-blacklist are all audit logged (the specific action plus, where the
    resident's `status` changes, a paired `resident.status_changed` entry).
    `resident.notice_cancelled` carries `cancelled_date` and
    `cancellation_reason` in `after`, and the notice's dates in `before`.
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
- [DECISION 2026-09-10] **`finalize_vacate` re-checks settlement under a row
  lock.** The view's `already_settled` guard runs outside any lock, so two
  concurrent `finalize` calls could both pass it and double-run the
  settlement (double refund audit, double bed release). The service now
  `select_for_update()` the `Vacate` row and re-raises `already_settled`
  before doing any work.
- [DECISION 2026-10-26] **The settlement preview does not net unpaid
  invoices against the refund.** `mark_absconded` forfeits the deposit
  against outstanding dues because leaving without notice is the
  penalised path; a normal vacate (give notice, then settle) is not — the
  owner's call was to surface `outstanding_dues` on the preview so staff
  see it before paying out, but leave collection a separate, later step
  rather than silently shrinking (or, if dues exceed the refund, zeroing
  out) a resident's deposit refund.
- [DECISION 2026-10-26] **No date validation was added to `finalize` or the
  preview.** `actual_vacate_date` still accepts any date — before the
  notice, before `notice_given_date`, or in the future — unlike `cancel`'s
  date, which is bounded. Flagged as a gap when the preview was proposed;
  the owner chose to leave finalize's existing behaviour as-is rather than
  bound it as part of this change. Revisit together if the product owner
  wants it tightened later.
- [DECISION 2026-10-26] **The settlement preview is a non-locking,
  point-in-time estimate.** Unlike `finalize_vacate`/`cancel_notice`, the
  preview service takes no row lock, so a `finalize` or `cancel` committed
  between the preview request and the next one can make the previewed
  figure stale. This is accepted rather than fixed: `finalize_vacate`
  already re-checks everything under its own lock (see the 2026-09-10
  decision above), so a stale preview can never cause a wrong settlement —
  at worst a staff member sees a number that is a few seconds old, the same
  risk as not reloading the screen. Locking a `GET` would not remove that
  window (the state can still change the instant after the response is
  sent) and would cost every preview a lock it doesn't need.

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

## Update 2026-10-04 — security deposit vs advance rent (owner decision)
- [DECISION] **Two separate amounts at admission.** `security_deposit_amount`
  (+ `_collected_date`, `_mode`) is the refundable deposit: never invoiced,
  refunded on vacate minus `maintenance_deduction`, forfeited against dues on
  absconded. `advance_amount` is rent paid upfront for the first period (~30
  days on a monthly contract); Module 08 applies it to the first issued
  invoice. Before this change `advance_amount` played the deposit role.
- [DECISION] **Surplus advance is refunded at leaving.** If the resident paid
  more than the first invoice (e.g. 2 months), the unapplied part
  (`advance_refundable = advance_amount - advance_applied_amount`) is added
  to `refund_amount` at vacate finalize. It is not credited to later invoices.
  On absconded it is forfeited with the deposit (assumed; confirm with owner).
- [DECISION] Migration 0007 moved existing `advance_*` values into the deposit
  fields (their old meaning) and zeroed the advance; renamed absconded record
  fields `advance_*` -> `deposit_*` (API break for clients reading them).
  `VacateSerializer` now also returns `security_deposit_amount` and
  `advance_refundable` as the refund breakdown.
- 2026-10-04  Migration 0007's advance->deposit data move now sets
  `app.is_super_admin` for its transaction. `admissions` is FORCE-RLS and the
  app role is not a superuser, so the first version updated zero rows without
  error. Covered by `DepositMigrationTests`.

## Update 2026-10-07 — cancel notice period (owner request)
A resident in Notice Period may ask to withdraw their notice and stay on. There
was no way back: `notice_period` only led to `vacated` or `blacklisted`, so this
needed a support data-fix.

- [DECISION] **`Vacate` is now a ForeignKey, not a OneToOne, with a partial
  unique index.** A resident who cancels will realistically give notice again
  months later, which a OneToOne forbids. The alternatives were deleting the row
  (destroys the record, against this module's append-only discipline) or keeping
  the OneToOne and blocking re-notice forever (unacceptable). `cancelled_date` /
  `cancellation_reason` / `cancelled_by` close a row, and
  `unique_open_vacate_per_resident` keeps at most one open per resident.
  `give_notice`'s `vacate_already_exists` check changed meaning accordingly
  (any row -> any *open* row); without that change no resident could ever give
  notice twice, which would have silently defeated the whole feature.
- [DECISION] **No cancellation deadline.** Allowed any time the resident is
  still in Notice Period and the vacate is unsettled, including after
  `expected_vacate_date` has passed. Nothing auto-vacates on that date, so an
  overstaying resident who decides to stay is a real case; blocking it would
  force a support data-fix, which is what this feature exists to remove.
- [DECISION] **`cancelled_date` is caller-supplied, defaulting to today.**
  Matches every other date in this module (`notice_given_date`,
  `actual_vacate_date`, `absconded_date`, `refund_date`). Backdating is open to
  any `manage_deposits` user — the same latitude `finalize` already gives on
  `actual_vacate_date`; no finer-grained date permission exists anywhere in the
  codebase. Future dates are rejected.
- [DECISION] **`cancellation_reason` is mandatory**, following the
  `write-off`/`note_required` precedent: this reverses a lifecycle event, so the
  audit trail is worth more than the convenience.
- [BUG FOUND] **`finalize_vacate` would have settled a cancelled notice.** It
  only checked `is_settled`, and set `resident.status = VACATED` with no
  transition check at all — so finalizing a withdrawn notice would have
  re-vacated an Active resident and freed their occupied bed. It now rejects
  `already_cancelled` and asserts the resident is still in their notice period,
  both inside the row lock.
- [DECISION] **One lock order for every workflow that writes
  `Resident.status`: `Resident` -> `Vacate` -> `Bed` -> `Subscription`**
  (`services.lock_resident`). No service locked the resident
  row before this, so `give_notice`, `cancel_notice`, `finalize_vacate`,
  `mark_absconded`, `confirm_blacklist` and Module 04's `change_status` all
  read-then-wrote `status` unguarded. Each now takes
  `select_for_update(of=('self',))` on the resident first and re-validates
  inside the lock. `of=('self',)` is required, not cosmetic: the callers'
  querysets `select_related` the nullable admission/allocation joins and
  PostgreSQL refuses `FOR UPDATE` on the nullable side of an outer join.
  This also closes a **pre-existing** race in `give_notice`, where two
  concurrent calls both passed the unlocked `exists()` check and the loser hit
  the unique index as an uncaught `IntegrityError` (a 500) instead of a 400.
- [BUG FOUND + FIXED] **Admission deadlocked against the generic status
  endpoint, and could double-activate.** `AdmissionViewSet.perform_create`
  locked `Bed -> Subscription` and only touched the resident at the very end
  (`resident.save()`, which takes an implicit row lock). Once `change_status`
  started locking `Resident -> Subscription`, a concurrent `Reserved -> Active`
  through both paths could deadlock: the PATCH holds the Resident and waits for
  the Subscription while admission holds the Subscription and waits to update the
  Resident. PostgreSQL aborts one side with `deadlock detected` and the
  untranslated error surfaces as a 500. Reproduced before fixing, 8 rounds each.
  Admission now locks the resident first, re-checks `can_transition_to(ACTIVE)`
  under that lock (`resident_not_ready_for_checkin`), then the bed, then
  `check_resident_limit` takes the Subscription — the same order as everything
  else.
  A **second defect, same cause**: the "must be Reserved" check lived only in the
  serializer, outside any lock, so a PATCH that activated the resident in the
  gap still let admission succeed and both requests reported success. The locked
  re-check fixes it; exactly one of them now wins and the other gets a 400.
  This corrects an earlier note in this spec that called admission a
  "known deviation" and said `Subscription` closes no cycle — that was only true
  until `change_status` took a resident lock, which is exactly what created it.
  `Subscription` is taken last on every path (`change_status`: after Resident;
  admission: after Resident and Bed), so it closes no cycle now. Covered by
  `test_lock_ordering.py` (real threads, separate connections).
- [DECISION] **Module 04's generic `PATCH /residents/{id}/status/` is guarded
  for this one transition** (`open_vacate_exists`), unlike the other gaps that
  module documents as accepted debt. A bare `notice_period -> active` flip would
  leave an open `Vacate` on an Active resident, which `give_notice` then reads
  as "already has a vacate record" — locking that resident out of ever giving
  notice again. Precedent: Module 13 added the plan-limit check to the same
  method for the same "consequential enough to guard" reason. Still allowed when
  there is no open vacate (a harmless data-fix path).
- Cancelling touches **nothing else**, and there are tests asserting so: the bed
  stays `OCCUPIED` (only `finalize` releases it), the `Allocation` and
  `contracted_rent` are unchanged (invariant 2 — never re-derived from the
  room's current rack rate), billing already treats Notice Period exactly like
  Active so the resident is invoiceable at the same rent on both sides, the
  deposit/advance are only paid out at finalize, and the plan-limit tally is
  unchanged (both statuses are in `COUNTS_TOWARD_PLAN_LIMIT`).
- `BedSerializer.history` (Module 02) now picks the vacate **by state** —
  `open_vacate` for a Notice Period resident, `latest_settled_vacate` for a
  Vacated one — because the newest row may be a cancelled notice whose dates
  must never read as a move-out. It prefetches via `vacate_prefetch()`, and a
  test asserts the query count does not grow with the number of occupants.
- 2026-10-07  Built: migration `0008_vacate_cancellation`,
  `POST /vacates/{id}/cancel/`, `services.cancel_notice`,
  `services.lock_resident`, the `finalize`/`give_notice` guards, the
  `change_status` guard, the `Notice Cancelled` timeline event and Telugu
  strings. 30 new tests (cancel lifecycle, non-disturbance of bed/allocation/
  rent, re-notice after cancel, both DB constraints, finalize-after-cancel
  rejection, date/reason validation, audit payloads, permissions + tenant
  isolation, state-aware occupancy display + N+1 guard, billing across the
  round trip, and two service-level concurrency tests for cancel-vs-finalize
  and double give-notice). Full suite (625) green.

## Update 2026-10-26 — settlement preview (owner request, mobile checkout)
The mobile app could give notice and cancel it, but had no way to show a
checkout screen's refund breakdown before calling `finalize`.

- [DECISION] **`Vacate.refund_for(maintenance_deduction)`** holds the refund
  formula; `refund_amount` (the settled figure) and the preview (an estimate
  for a not-yet-chosen deduction) both call it, so they can't drift apart.
- [DECISION] **`VacateFinalizeSerializer` now subclasses a new
  `VacateSettlementPreviewSerializer`**, which holds `maintenance_deduction`
  and its validation (non-negative, capped at the deposit). One set of rules
  for both endpoints, enforced in one place.
- [DECISION] **The preview's response fields use `max_digits=None`,
  not `MONEY_KWARGS`.** `refund_amount` sums two 12-digit money fields and
  `outstanding_dues` sums across invoices — either can legitimately exceed
  the 12-digit cap a single stored column is held to (invariant 5), and a
  12-digit response field would then fail to serialize an otherwise-valid
  total.
- See the three Decisions above (dues not netted, no new date rules, preview
  is a non-locking estimate) for the owner calls this shipped against.
- Built: `GET /vacates/{id}/settlement-preview/`,
  `services.settlement_preview`, `Vacate.refund_for`,
  `VacateSettlementPreviewSerializer`,
  `VacateSettlementPreviewResponseSerializer`. 18 new tests (formula parity
  with finalize, default/validation of the deduction, dues summed but not
  netted, rejected once settled/cancelled, read-only/no-audit-log guarantee,
  permission + tenant-isolation scoping, large-aggregate precision). Schema
  completeness test extended to cover the new query parameter and typed
  response.
- 2026-10-30  Module 24: move-out pays unused food-holiday credit with the refund and claws back days
  credited on an issued bill after the actual vacate date. Clawback is capped at the refund; calculated,
  recovered and unrecovered amounts are stored on `vacates`, and `refund_for` = deposit − deduction +
  advance + credit − recovered. Abscond adds the credit to the netted pool and the clawback to the dues
  (`absconded_records.food_holiday_credit/_clawback`). `settlement-preview` takes `?actual_vacate_date=`
  and returns the figures from the same read-only plan. `finalize_vacate` and `mark_absconded` now lock
  Settings before Resident.

## Update 2026-11-01 — security deposit paid in parts (owner request)
Residents often pay only part of the money on joining (₹3,000–4,000 of ₹12,000 rent + ₹5,000 deposit) and the
rest days later. The admission wizard used to show one "Total Due" and record everything as paid, and it sent
rent + deposit as the *rent advance* (so the deposit was applied to the first invoice and `security_deposit_amount`
stayed ₹0 — a money bug, fixed here). Rent paid late already worked (the advance is applied to the first
invoice; a shortfall stays due on it). The deposit had one fixed number and admissions are immutable, so a later
deposit payment could not be recorded. Now it can.

- [DECISION] **`security_deposit_amount` keeps meaning "collected so far"; the agreed total is new.**
  `Admission.security_deposit_agreed` (default 0) is what the resident owes;
  `security_deposit_pending = max(agreed − collected, 0)` is a property, never stored. Every existing reader
  (vacate refund, settlement preview, the `deduction_exceeds_deposit` cap, the absconded forfeit, the "deposits
  held" report) already reads `security_deposit_amount`, so each one automatically counts only money that was
  received. **A pending deposit is not a due**: it is never invoiced, it only lowers what can be refunded or
  forfeited. (An admission created before this field, or outside the API, can have collected > agreed; pending
  is then 0, never negative.)
- **Ledger.** New `DepositPayment` (table `deposit_payments`, RLS-enforced; `admission` PROTECT FK, `amount`,
  `payment_date`, `payment_mode` upi/cash/bank_transfer, `reference`, `recorded_by`, `idempotency_key` with a
  partial unique constraint per tenant, like payments). `security_deposit_amount` is its running total, updated
  under the admission row lock. The deposit collected at check-in becomes the first ledger row (same
  transaction as the admission).
- **Admission create** accepts `security_deposit_agreed`. Omitted, it defaults to `security_deposit_amount`, so
  older clients (the Flutter app, a cached PWA) behave as before. `security_deposit_amount > agreed` is rejected
  (`deposit_exceeds_agreed`). `advance_amount` may be `0.00`. A collected amount still needs its date and mode.
- **`POST /api/v1/deposit-payments/`** `{resident, amount, payment_date, payment_mode, reference?}` records the
  rest; `GET` lists (`?resident=`). `manage_deposits`, property-scoped like admissions, append-only (no
  update/delete), `Idempotency-Key` honoured (same key + same body = 200 replay with
  `Idempotent-Replayed: true`; same key + different body = 409). `services.record_deposit_payment` locks
  **Resident → Admission** (resident first, like every workflow that touches the resident), then re-checks under
  the locks: resident Active or Notice Period (`resident_not_current`), `0 < amount ≤ pending`
  (`deposit_overpaid`). Audit-logged as `deposit.payment_recorded` with the collected amount before and after.
- `ResidentSerializer` and `AdmissionSerializer` return `security_deposit_agreed` / `_pending`; the resident
  fields are hidden from roles without `view_finance`/`manage_deposits`, like `security_deposit_amount`.
- **Migration 0010** adds the field and table, enables RLS, and backfills under the super-admin GUC (the lesson
  of 0007): `agreed = collected`, and one ledger row per admission that had collected a deposit (its own date and
  mode; a legacy row with no mode becomes cash). Reverse of the backfill is a no-op.
- **Account deletion (Module 22):** `residents.DepositPayment` is in `DISPOSITION` and `PURGE_ORDER` ahead of
  `Admission` (the PROTECT FK would otherwise block the purge); the purge end-to-end test now seeds one.
- **Frontend.** Wizard step 4 shows Agreed / Paid now / Pending for rent and deposit (both start at the full
  amount, editable down to 0; paid > agreed is blocked), asks for mode and date only when something is paid, and
  sends `advance_amount` = rent paid now, `security_deposit_agreed`, `security_deposit_amount` = deposit paid now.
  **Card is removed** (the API only accepts upi/cash/bank_transfer). The step-3 agreed-rent field is read-only:
  the contracted rent is the room's rate, snapshotted server-side (invariant 2), so editing it never did anything.
  The resident profile shows agreed / collected / pending and a "Record deposit payment" dialog (needs
  `manage_deposits`; Active/Notice Period only).
- Tests: `residents/tests/test_deposit_payments.py` (30: partial admission, defaults, rejection, later payment,
  audit, idempotency, permissions and scoping, refund/forfeit use collected only, backfill under RLS, tenant
  isolation). Frontend: `AdmissionWizard.preselect.test.tsx` (the collection step), `RecordDepositPaymentDialog.test.tsx`,
  `ResidentProfile.kyc.test.tsx` (the deposit block) and `money.test.ts`.
- Not done: nothing reminds staff of a pending deposit, and it is not shown in the dues list or on
  receipts; a pending deposit is visible on the resident profile only. Ask the owner before adding either.

## Update 2026-11-11 — held advance balance & Milestone 1 exit preview
- [DECISION] **Held advance may be adjusted against later invoices.** `advance_amount - advance_applied_amount` (`advance_refundable`) decreases whenever the automatic first-invoice application OR an explicit `"Adjust from advance"` payment (`POST /api/v1/invoices/{id}/adjust-advance/`) draws it down, and is restored when an advance-adjustment payment is deleted while the resident is still Active or Notice Period. Only unapplied advance remaining at vacating (`advance_refundable`) is refunded in `Vacate.refund_for()`; advance already applied to rent is never refunded again.
- **Locking:** `finalize_vacate` locks `Settings -> Resident -> Vacate -> Admission`, and `mark_absconded` locks `Settings -> Resident -> Admission`, preventing races between vacate/abscond settlement and concurrent advance adjustments or payment reversals.
- **Serializers:** `VacateSerializer` and `GET /vacates/{id}/settlement-preview/` now return `advance_amount` and `advance_applied_amount` alongside `advance_refundable` and `security_deposit_amount` so the UI shows collected advance vs already-applied vs refundable balance (`VacateSettlementPreviewResponseSerializer` updated in `apps/residents/schema.py`).
- **Refund payout timing limitation:** `Vacate` finalization calculates `refund_amount` due and optionally stores `refund_date` / `refund_mode`, but does not yet represent a verified cash outflow ledger event; analytics/reporting therefore keep `refunds_paid = 0.00` until actual refund payouts are tracked cleanly (Milestone 2 / follow-up).
- **Web Milestone 1 UI:** Resident Profile renders the Held Advance breakdown and a read-only **Exit Settlement Preview** card for `notice_period` residents (`GET /vacates/?resident=` + `settlement-preview`, keeping `outstanding_dues` separate). Interactive notice/cancel/finalize vacate dialogs remain deferred to Milestone 2 (`FE-10`). Tests: `residents/tests/test_vacates.py`, `billing/tests/test_payment_integrity.py`, frontend `ResidentProfile.kyc.test.tsx`.
