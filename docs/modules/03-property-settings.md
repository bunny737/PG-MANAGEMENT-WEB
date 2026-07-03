# Module: Property Settings

> Keep this file in sync with the code AT ALL TIMES.
> If the code and this file disagree, this file is wrong — fix it in the same commit.

**Status:** Done
**Phase:** 1
**PRD reference:** Module 2B (Property Settings)
**Depends on:** 02
**Blocks:** 08

## Purpose
Owner/Manager configure per-property billing behaviour: when a new rent
takes effect after a room transfer, and whether/how a late-payment penalty
is charged. Different properties under the same tenant can have different
settings. Module 06 (transfers) and Module 08 (billing) read these values;
this module only owns storage + validation.

## Data model (as-built)

```
Table: property_settings                         (RLS enforced)
  id                        uuid PK
  tenant_id                 uuid            (RLS)
  property                  OneToOne -> properties  (exactly one row per property)
  room_transfer_rent_timing immediate | next_billing_cycle   (default: next_billing_cycle)
  late_payment_penalty_type none | fixed | percentage        (default: none)
  penalty_value             decimal(12,2) null   (₹ or %, required unless type=none)
  penalty_grace_days        positive smallint, 0-30 (default: 5)
  penalty_applies_to        full_invoice | outstanding_balance  (default: full_invoice)
  penalty_compounding       one_time | monthly    (default: one_time)
  created_at / updated_at
```
No field exists for PRD Setting 2 ("Shared Invoices") — it's a fixed rule
(always one invoice per resident), not a toggle. See Decisions.

## API endpoints
```
GET|PATCH  /api/v1/properties/{id}/settings/    per-property billing settings   manage_property_settings
```
Nested action on `PropertyViewSet` (not a standalone router) since it's a
1:1 singleton keyed by property, not a list resource.

## Business rules (each maps to a test)
1. Every property has exactly one settings row, lazily created with PRD
   defaults (`next_billing_cycle` / no penalty / 5 grace days / full
   invoice / one-time) on first `GET` or `PATCH` — no separate create
   endpoint.
2. `penalty_value` is required whenever `late_payment_penalty_type` is
   `fixed` or `percentage`; switching the type back to `none` clears any
   stored value (invariant: a "no penalty" row never carries a stray amount).
3. A `percentage` penalty must be `0 < value <= 100`.
4. `penalty_grace_days` is capped at 30 (PRD summary table: "0-30 days").
5. `manage_property_settings` = Super Admin, Owner, **and Manager** (see
   Decisions — this widens the Module 01 permission matrix). Receptionist
   and Resident get 403.
6. A Manager can only read/update settings for properties they're assigned
   to (PRD §6) — enforced for free by reusing `PropertyViewSet.get_object()`,
   which already scopes to `services.visible_property_ids`. An unassigned
   or cross-tenant property ID returns 404, not 403.
7. Settings changes write an audit log with before/after values.
8. `property_settings` is RLS-enforced like every table since Module 02.

## Permissions
- `manage_property_settings` (Super Admin, Owner, Manager): read/update.
- Receptionist and Resident: no access (403).

## Edge cases handled
- Patching only `penalty_grace_days` while a penalty type is already set
  doesn't require re-sending `penalty_value` (partial update; `validate()`
  falls back to the existing instance value).
- Manager assigned to the property mid-session immediately gets access on
  their next request — no caching of the assignment check.

## Open questions / Decisions
- [DECISION 2026-07-03] **PRD conflict resolved with the product owner:**
  PRD §6's Permission Matrix table listed `manage_property_settings` as
  Owner-only, but PRD Module 2B's prose ("accessible by Owner and Manager")
  and its own settings summary table ("Configurable By: Owner, Manager")
  both included Manager. Module 2B was confirmed correct; `PERMISSION_MATRIX`
  in `apps/core/roles.py` (a Module 01 file) was widened accordingly — see
  the Module 01 spec's Decisions/Changelog for the cross-reference.
- [DECISION 2026-07-03] `PropertySettings` lives in `apps.properties` (same
  app as Module 02), not a new Django app — it's a straight extension of
  Property, same as `PropertyStaffAssignment`.
- [DECISION 2026-07-03] Exposed as a nested `@action` on `PropertyViewSet`
  (`/properties/{id}/settings/`) rather than a flat router — there's no
  "list" semantics, it's always exactly one row per property. The action
  method is named `property_settings`, not `settings` — a ViewSet method
  literally named `settings` shadows `APIView.settings` (DRF's internal
  `api_settings` reference) and breaks exception handling for the whole
  viewset; this cost a debugging pass, worth flagging for future modules
  that add nested actions.
- [DECISION 2026-07-03] PRD Setting 2 (Shared Invoices) has no field —
  it's documented as a fixed, non-configurable rule; Module 08 enforces it
  structurally (one invoice per resident) rather than checking a flag here.
- [DECISION 2026-07-03] Penalty *waiver* (PRD: "management can waive a
  penalty on a per-invoice basis with a mandatory note, audit logged") is
  invoice-level, not property-settings-level — that's Module 08's concern,
  not built here.
- [OPEN] `penalty_applies_to` / `penalty_compounding` are stored and
  validated for shape, but not yet exercised by any billing logic — Module
  08 is where they'll actually be read.

## Changelog
- 2026-06-xx  Created stub.
- 2026-07-03  Built: `PropertySettings` model (RLS), lazy get-or-create,
  penalty validation rules, nested `/properties/{id}/settings/` endpoint,
  audit logging, 10 tests. Also widened `manage_property_settings` to
  include Manager (Module 01 correction). Spec rewritten to as-built.
