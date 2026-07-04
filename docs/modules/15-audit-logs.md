# Module: Audit Logs

> Keep this file in sync with the code AT ALL TIMES.
> If the code and this file disagree, this file is wrong — fix it in the same commit.

**Status:** Done
**Phase:** 3
**PRD reference:** Module 21 (Audit Logs); API Groups list (`/api/v1/audit-logs/`)
**Depends on:** 01
**Blocks:** none

## Purpose
Every module writes to the audit trail as it goes (invariant 9, via
`apps.audit.log.record` — built in Module 01 so logging could start from day
one). This module adds the read side: a filterable query API so an Owner can
see what happened in their tenant, and Super Admin can see everything,
including platform-level actions (tenant signup, suspension) that have no
single owning tenant.

## Data model (as-built)
No new table — `AuditLog` (RLS enforced) has existed since Module 01:
```
Table: audit_logs                               (RLS enforced, app: apps.audit)
  id                uuid PK
  tenant_id         uuid, null       (RLS — null = platform-level action)
  actor             FK -> users, null (SET_NULL)
  action            varchar(100), indexed   e.g. 'staff.role_changed'
  object_type       varchar(100), blank
  object_id         varchar(64), blank
  before            jsonb, null
  after             jsonb, null
  ip_address        inet, null
  created_at        datetime
```
This module adds no migration — only a permission entry and the query API.

## API endpoints
```
GET /api/v1/audit-logs/           list (filterable)     view_audit_logs
GET /api/v1/audit-logs/{id}/      retrieve               view_audit_logs
```
No create/update/delete — the log is append-only; every write goes through
`apps.audit.log.record`, never the API.

Filters (`?param=value`, django-filter): `action`, `object_type`, `object_id`,
`actor`, `tenant_id` (Super Admin only, in practice — see below),
`created_at__gte`, `created_at__lte`. Default ordering: newest first
(`Meta.ordering`, unchanged from Module 01).

## Business rules (each maps to a test)
1. Owner sees only their own tenant's log entries. RLS already enforces this
   at the DB level (the GUC `app.tenant_id` is set to the Owner's tenant by
   `TenantJWTAuthentication`); the viewset's `get_queryset` also filters
   explicitly by `tenant_id`, matching every other tenant-scoped viewset in
   the codebase (defense-in-depth, not load-bearing).
2. Super Admin sees every entry, including platform-level ones
   (`tenant_id=null` — e.g. `tenant.signed_up`), since their JWT sets
   `is_super_admin=True` which bypasses RLS entirely. `?tenant_id=<uuid>`
   narrows to one tenant's entries.
3. `view_audit_logs` is Owner + Super Admin only — Manager and Receptionist
   get 403. Unlike most other Owner+Manager (`_OPS`) permissions, the audit
   trail covers staff role changes and other tenant-wide actions a property
   Manager shouldn't necessarily see (see Decisions).
4. Filtering by `object_type` + `object_id` together returns the full history
   for one record (e.g. every audit entry about a specific Resident) —
   directly useful for "what happened to this invoice/resident" lookups.
5. `audit_logs` is RLS-enforced; isolation proven directly against the
   queryset (bypassing the API) as well as through the API.

## Permissions
- `view_audit_logs` (Super Admin, Owner): list, retrieve.
- Manager, Receptionist, Resident: no access.

## Edge cases handled
- An Owner requesting another tenant's log entry by id gets 404 (RLS hides
  the row entirely — same as every other cross-tenant lookup elsewhere).
- A log with `actor=null` (the actor's user account was deleted — `SET_NULL`)
  serializes `actor` as `null` rather than erroring.
- Date-range filtering (`created_at__gte`/`__lte`) accepts standard ISO
  datetimes and composes with the other filters.

## Open questions / Decisions
- [DECISION 2026-07-04] **`view_audit_logs` excludes Manager**, unlike the
  `_OPS` group (Super Admin/Owner/Manager) used for most operational
  permissions. The PRD §6 matrix has no row for this permission at all — it
  predates Module 21 — so this module had to choose. Audited actions include
  things a Manager shouldn't necessarily see tenant-wide (another Manager's
  or Receptionist's actions, staff role changes, discount approvals across
  properties they aren't assigned to), so it was scoped alongside the other
  strictly-Owner-only rows (`manage_subscription`, `manage_staff_accounts`,
  `assign_staff_to_properties`) rather than `_OPS`. Revisit if the product
  owner wants Managers to see audit history scoped to their assigned
  properties specifically.
- [DECISION 2026-07-04] **No pagination.** The project has no
  `DEFAULT_PAGINATION_CLASS` configured anywhere, so this viewset returns a
  plain list like every other list endpoint in the codebase — consistent,
  not a new precedent. Large tenants may want cursor pagination eventually;
  deferred until it's a real problem (matches how every other list endpoint
  in this codebase has been left unpaginated so far).
- [DECISION 2026-07-04] **No write endpoints.** `apps.audit.log.record` is
  the only way to create a row — by design, since every module already calls
  it directly and an API write path would let a client fabricate history.
- [OPEN] The PRD's `/api/v1/audit-logs/` entry has no detailed field spec
  beyond the "Audited Actions" example list (Module 21) — this module's
  filter set was designed from first principles (action/object/actor/date),
  not a PRD table. Revisit if the frontend needs a different shape.

## Changelog
- 2026-06-xx  Created stub.
- 2026-07-02  `AuditLog` model + RLS + `apps.audit.log.record()` write helper
  built in Module 01 so every module could log from day one (see that
  module's changelog).
- 2026-07-04  Built the read side: `AuditLogSerializer`, `AuditLogViewSet`
  (read-only, tenant-scoped for Owner / unscoped + tenant-filterable for
  Super Admin, action/object/actor/date filters), `view_audit_logs`
  permission (Owner + Super Admin) added to `PERMISSION_MATRIX`, admin
  registration (read-only). 12 new tests (scoping, permission gating,
  filters, ordering, RLS isolation). Full suite (381) green. Spec written
  to as-built.
