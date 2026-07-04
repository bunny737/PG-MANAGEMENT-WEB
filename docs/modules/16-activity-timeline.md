# Module: Activity Timeline

> Keep this file in sync with the code AT ALL TIMES.
> If the code and this file disagree, this file is wrong — fix it in the same commit.

**Status:** Done
**Phase:** 3
**PRD reference:** Module 22 (Activity Timeline)
**Depends on:** 04
**Blocks:** none

## Purpose
A single chronological feed of everything that's happened to one resident —
inquiry, reservation, admission/check-in, invoices, payments, transfers,
complaints, and (down one of two mutually-exclusive exit paths) either a
normal vacate or an absconded + blacklist sequence. Computed on request from
records Modules 04-12 already write; nothing is stored twice.

## Data model (as-built)
No new table. `GET /residents/{id}/timeline/` aggregates, at read time:
`Resident` (creation), `AuditLog` (the one status transition — Reserved —
with no dedicated model timestamp), `Admission`, `Invoice` + `Payment`,
`Transfer`, `Complaint`, `Vacate`, `AbscondedRecord`, `BlacklistEntry`.

## API endpoints
```
GET /api/v1/residents/{id}/timeline/    chronological event feed    view_activity_timeline
```

Response: a JSON array, oldest first, each item
`{"date": "YYYY-MM-DD", "event": "<label>", "detail": "<string, may be blank>"}`.

## Business rules (each maps to a test)
1. Every event date is sourced from an existing field — nothing is invented.
   The one exception with no dedicated timestamp is the Inquiry → Reserved
   transition, which has no model field of its own (Module 04's generic
   status endpoint just flips `status`); it's read from the paired
   `AuditLog(action='resident.status_changed', after__status='reserved')`
   entry that endpoint already writes.
2. Admission + Check-In collapse into **one** event
   (`Admission Completed — Checked In`), not the PRD example's two lines —
   in this system they are one atomic action (Module 05), so presenting them
   as two separate events would imply a sequencing that doesn't exist.
3. `Invoice Generated` fires on `issue_date` (not draft creation) — same
   "issued is the real obligation" reasoning as Module 14's invoice-issued
   notification.
4. `Invoice Overdue` is derived, not stored (consistent with `is_overdue()`
   in Module 08/09): only appears for an invoice that is *currently*
   `is_overdue(today)` — i.e. still not `paid`. A later-settled invoice's
   overdue period silently drops off the timeline once it's fully paid,
   same as the invoice's own `is_overdue` flag elsewhere in the API.
5. Each `Payment` becomes one event, labeled by its effect on the invoice's
   running total (not a stored field): `Partial Payment` if it leaves a
   balance, `Remaining Paid` if it's the *last of several* payments that
   clears the balance, `Payment Received` if a single payment clears it
   outright.
6. A `Transfer` names its destination room + bed.
7. `Complaint Raised` fires once per complaint, at creation.
8. Exactly one of two exit sequences can appear (Module 04's status machine
   only allows one): `Notice Given` → `Vacated` (with refund amount), or
   `Marked Absconded` (+ `Advance Forfeited` if any advance was applied) →
   optionally `Dues Written Off` → optionally `Blacklisted`.
9. Same-day events are ordered by a fixed per-kind weight (assigned in
   narrative order inside `build_activity_timeline`), not insertion order —
   so a day with several events (e.g. Absconded + Advance Forfeited, both
   dated `absconded_date`) always reads in a sensible sequence regardless of
   which database row happened to be written first.
10. `view_activity_timeline` (Super Admin, Owner, Manager — **not**
    Receptionist) gates the endpoint; Manager is further scoped to assigned
    properties via the same `get_object()` the rest of `ResidentViewSet`
    already uses (a Manager not assigned to the resident's property gets
    404, identical to every other resident sub-resource).

## Permissions
- `view_activity_timeline` (Super Admin, Owner, Manager): the one action.
- Receptionist, Resident: no access (see Decisions — this is a narrower
  gate than `view_resident_profile`, which does include Receptionist).

## Edge cases handled
- A resident with no admission yet (`Inquiry`/`Reserved`) returns a
  one-or-two-event timeline, not an error.
- Complaints/transfers/invoices with zero rows simply contribute nothing —
  no placeholder events.
- An `AbscondedRecord` with no advance to forfeit (`advance_applied_to_dues
  == 0`, e.g. no advance was ever collected) omits the `Advance Forfeited`
  line entirely rather than showing "₹0.00 forfeited".

## Open questions / Decisions
- [DECISION 2026-07-04] **Computed, not stored.** PRD Module 22 describes a
  read-only feed; there is no "add a timeline entry" use case anywhere in
  the PRD, and every fact it needs already lives in another module's table.
  Storing a redundant copy would just be another thing to keep in sync
  (violates the same "never store what can be derived" discipline as
  `Invoice.total`, `Room.current_occupancy`, etc.).
- [DECISION 2026-07-04] **Gated by a new `view_activity_timeline` permission
  (`_OPS`: Super Admin/Owner/Manager), not the Receptionist-inclusive
  `view_resident_profile`.** The feed surfaces invoice/payment amounts, and
  Receptionist has neither `manage_invoices` nor `manage_payments` — letting
  Receptionist reach the same figures through the timeline would be a real
  permission leak, not just an inconsistency.
- [DECISION 2026-07-04] **`Dues Written Off`'s date is `AbscondedRecord.
  updated_at`**, since that model has no dedicated "written off at"
  timestamp (only `dues_written_off_by`/`_note`). This is an approximation —
  `updated_at` reflects the last save on that row, which in practice is only
  ever the write-off action itself (the record has no other post-creation
  mutation path), so it's accurate today but would silently go wrong if a
  future change added another field write to `AbscondedRecord`. Flagged here
  so that future change remembers to add a real timestamp if needed.
- [DECISION 2026-07-04] **No new circular-import workaround needed.** Unlike
  `outstanding_dues_for` (which defers its `Invoice` import inside the
  function body to dodge `apps.billing` importing `apps.residents` at load
  time), `build_activity_timeline` never imports `apps.billing`/
  `apps.operations` models at all — it walks the reverse relations Django
  already registers on `Resident` (`resident.invoices`, `resident.
  complaints`, `resident.transfers`, ...), which exist regardless of import
  order.
- [OPEN] Visitor logs (Module 12) are not included — the PRD's Module 22
  example timeline has no visitor entries, and visitors are a front-desk
  operational log rather than a resident-lifecycle milestone. Revisit if the
  product owner wants them folded in.
- [OPEN] Discount applied/modified (mentioned in the PRD's Module 21 audit-
  action examples, not Module 22's timeline example) isn't a timeline event
  either — kept the scope to literally what Module 22's example shows plus
  the plumbing needed to make it real. Easy to add later:
  `resident.discounts.all()` reverse relation already exists.

## Changelog
- 2026-06-xx  Created stub.
- 2026-07-04  Built `apps.residents.services.build_activity_timeline` (no new
  model/migration) aggregating Resident/AuditLog/Admission/Invoice/Payment/
  Transfer/Complaint/Vacate/AbscondedRecord/BlacklistEntry into one sorted
  feed; `GET /residents/{id}/timeline/` action on `ResidentViewSet`; new
  `view_activity_timeline` permission (Super Admin/Owner/Manager). 13 new
  tests (event sourcing per PRD example, chronological ordering incl.
  same-day tie-breaks, both exit-path branches, permission scoping incl.
  Manager property-assignment 404). Full suite (394) green. Spec written to
  as-built.
