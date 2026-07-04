# Module: Complaints

> Keep this file in sync with the code AT ALL TIMES.
> If the code and this file disagree, this file is wrong — fix it in the same commit.

**Status:** Done
**Phase:** 3
**PRD reference:** Module 12 (Complaint Management)
**Depends on:** 04
**Blocks:** none

## Purpose
Staff (Super Admin/Owner/Manager) log a resident's complaint/maintenance
ticket, assign it to a staff member, and drive it through an exact linear
workflow (Open → Assigned → In Progress → Resolved → Closed) with a
comments thread and an optional photo/file attachment.

## Data model (as-built)

```
Table: complaints                               (RLS enforced, app: apps.operations)
  id                uuid PK
  tenant_id         uuid              (RLS)
  resident          FK -> residents.Resident (PROTECT)
  category          electrical | plumbing | internet_wifi | housekeeping |
                    security | furniture | other
  priority          low | medium | high | urgent   (default medium)
  status            open | assigned | in_progress | resolved | closed
                    (default open)
  description       text
  attachment        file, null       (photo/file upload)
  assigned_to       FK -> users, null (SET_NULL)
  raised_by         FK -> users, null (SET_NULL)   -- staff who logged it
  created_at / updated_at

Table: complaint_comments                       (RLS enforced, app: apps.operations)
  id                uuid PK
  tenant_id         uuid              (RLS)
  complaint         FK -> complaints (CASCADE)
  author            FK -> users, null (SET_NULL)
  body              text
  created_at / updated_at
```

## API endpoints
```
GET|POST   /api/v1/complaints/                 list / log a complaint            manage_complaints
GET|PATCH  /api/v1/complaints/{id}/             retrieve / edit while open        manage_complaints
POST       /api/v1/complaints/{id}/assign/      Open -> Assigned                  manage_complaints
PATCH      /api/v1/complaints/{id}/status/      Assigned->In Progress->Resolved->Closed  manage_complaints
GET|POST   /api/v1/complaints/{id}/comments/    comments thread                   manage_complaints
```
No DELETE — a complaint is never removed, only closed.

## Business rules (each maps to a test)
1. Logging a complaint (`POST /complaints/`) defaults `status=open`,
   `priority=medium`, stamps `raised_by` from the request user; `resident`
   must be in a property the actor can see (`property_not_assigned`).
2. `category`/`priority`/`description`/`attachment` are editable only while
   `status=open` (`complaint_not_open`) — once assigned, the core facts of
   the ticket are locked, matching Module 08/10's "once the record enters a
   workflow, only dedicated actions mutate it further" discipline.
3. **Assign** (`POST /complaints/{id}/assign/`) requires the complaint be
   `open` and moves it to `assigned`. `assigned_to` must (a) belong to the
   same tenant (`cross_tenant_assignee`), (b) hold `manage_complaints`
   permission (`assignee_not_staff` — no assigning to a Receptionist or
   Resident), and (c) be able to see the resident's property
   (`assignee_not_assigned`, reusing `can_view_property` against the
   *assignee*, not the actor).
4. **Status transitions** (`PATCH /complaints/{id}/status/`) follow the PRD
   workflow's exact edges (invariant 8 style) — `open→assigned`,
   `assigned→in_progress`, `in_progress→resolved`, `resolved→closed`; no
   skipping stages, no reopening a closed complaint
   (`invalid_status_transition`). Reaching `assigned` through this endpoint
   is explicitly rejected (`use_assign_action`) — assignment always goes
   through the dedicated action so `assigned_to` is never left unset.
5. The **comments thread** (`GET`/`POST /complaints/{id}/comments/`) is open
   at any status (including `closed`) — a post-closure note is still valid.
   Each comment stamps `author` from the request user.
6. Creating, editing, assigning, changing status, and commenting are all
   audit logged.
7. `manage_complaints` (Super Admin, Owner, Manager) gates every endpoint —
   Receptionist and Resident get 403 (PRD §6 matrix: Receptionist has no
   complaint access at all, unlike `view_resident_profile`). Scoped to the
   actor's assigned properties via the resident's property.
8. `complaints`/`complaint_comments` are RLS-enforced (isolation proven).

## Permissions
- `manage_complaints` (Super Admin, Owner, Manager): every endpoint, scoped
  to assigned properties for Manager.
- Receptionist and Resident: no access (see Decisions on `raise_complaint`).

## Edge cases handled
- Assigning to an Owner (who is always implicitly visible on every
  property) succeeds without an explicit `PropertyStaffAssignment` row,
  same as `can_view_property`'s existing Owner/Super Admin short-circuit.
- Double-assigning an already-`assigned` complaint is rejected
  (`complaint_not_open`), not silently overwritten.
- A `closed` complaint rejects every further status transition, including
  back to `in_progress`.

## Open questions / Decisions
- [DECISION 2026-07-04] **`raise_complaint` (Resident self-service) is not
  implemented.** The PRD lists Resident as a self-service role
  ("Raise and track complaints"), but Module 04 already confirmed with the
  product owner that Resident profiles have no linked login `User` account
  yet ([OPEN] in `04-residents.md`) — there is no way for an actual resident
  to authenticate and hit a `raise_complaint`-gated endpoint today. Rather
  than build an endpoint nothing can call, this module only implements the
  staff side (`manage_complaints`: log a complaint on a resident's behalf,
  e.g. front-desk receiving a phone-in report). `ComplaintComment.author`
  and `Complaint.resident` are both already resident-shaped (generic User
  FK / Resident FK), so true self-service drops in later with zero schema
  change once resident login is resolved.
- [DECISION 2026-07-04] **App placement:** `Complaint`/`ComplaintComment`
  live in `apps.operations` — the app was pre-scaffolded for Modules 11/12
  (Module 05's placement-decision note called this out explicitly), so this
  is its first real content.
- [DECISION 2026-07-04] **Exact linear status graph, no reopening.** The
  PRD draws a single-line workflow (`Open → Assigned → In Progress →
  Resolved → Closed`) with no branches, unlike Resident's status graph
  which explicitly branches (Absconded/Blacklisted). Applied the same
  "STATUS LIFECYCLES are exact" rigor (invariant 8) rather than assuming an
  implicit reopen/skip allowance. Revisit if the product owner wants a
  resolved-but-unsatisfied resident to reopen a ticket.
- [DECISION 2026-07-04] **Editing is locked once assigned, not once
  resolved/closed.** PRD doesn't specify an edit-lock point at all; `open`
  was chosen as the cutover because that's the moment the ticket enters a
  tracked workflow with an owner (`assigned_to`) — same rationale as
  Module 08 locking an invoice at `issued`, not at `paid`.
- [OPEN] SLA tracking and Complaint Reports (open tickets, average
  resolution time) are explicitly PRD V2/deferred — not built.

## Changelog
- 2026-06-xx  Created stub.
- 2026-07-04  Built: `Complaint` + `ComplaintComment` (RLS, `apps.operations`)
  with an exact linear status graph, a dedicated `assign` action (validates
  the assignee's tenant/permission/property visibility), open-only field
  editing, a comments thread, and audit logging on every mutation. 30 tests
  (creation/edit, assignment validation, status transitions, comments,
  permission scoping, RLS isolation); full suite (287) green. Spec written
  to as-built.
