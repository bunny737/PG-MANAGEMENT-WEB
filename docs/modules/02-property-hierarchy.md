# Module: Property Hierarchy

> Keep this file in sync with the code AT ALL TIMES.
> If the code and this file disagree, this file is wrong — fix it in the same commit.

**Status:** Done
**Phase:** 1
**PRD reference:** Module 2 (Property Management), Module 2B (Property Settings —
billing/penalty fields deferred to Module 03), Module 3 (Room Management),
Module 4 (Bed Management), PRD §6 (Property Assignment Rules)
**Depends on:** 01
**Blocks:** 03, 04, 13

## Purpose
Owner builds the Property → Floor → Room → Bed hierarchy for each of their
PGs/hostels, and assigns Manager/Receptionist staff to the specific
properties they're allowed to work on. Every later module (residents,
admissions, allocations, billing) hangs off this hierarchy.

## Data model (as-built)

```
Table: properties                   (RLS enforced)
  id                uuid PK
  tenant_id         uuid            (RLS)
  name              varchar(200)
  property_type     boys_hostel | girls_hostel | pg | co_living
  address_line / city / state / country
  contact_number    varchar(15)     contact_email  blank-allowed
  status            active | inactive
  created_at / updated_at
  -- floors_count / rooms_count / beds_count are computed in the
  -- serializer (child counts), never stored — avoids drift.

Table: floors                       (RLS enforced)
  id                uuid PK
  tenant_id         uuid            (RLS)
  property          FK -> properties
  name              varchar(100)    e.g. "Ground Floor"
  order             positive smallint  (unique per property — display order)
  created_at / updated_at

Table: rooms                        (RLS enforced)
  id                uuid PK
  tenant_id         uuid            (RLS)
  floor             FK -> floors
  room_number       varchar(20)     (unique per floor)
  sharing_type      1 | 2 | 3 | 4   (IntegerChoices — also the bed capacity)
  category          ac | non_ac
  rack_rate_with_food      decimal(12,2)
  rack_rate_without_food   decimal(12,2)
  status            available | occupied | reserved | maintenance
                    (auto-synced from bed statuses; `maintenance` is a
                    manual override that sync will not clear — see Decisions)
  created_at / updated_at

Table: beds                         (RLS enforced)
  id                uuid PK
  tenant_id         uuid            (RLS)
  room              FK -> rooms
  bed_number        varchar(20)     (unique per room, e.g. "201-A")
  rack_rate_with_food_override     decimal(12,2) null
  rack_rate_without_food_override  decimal(12,2) null
  status            available | occupied | reserved | maintenance
  created_at / updated_at

Table: property_staff_assignments   (RLS enforced)
  id                uuid PK
  tenant_id         uuid            (RLS)
  staff             FK -> users (role must be manager/receptionist)
  property          FK -> properties
  created_at / updated_at          (unique per staff+property)
```

## API endpoints
```
GET|POST    /api/v1/properties/                          list/create        manage_properties (write) / owner+manager+receptionist (read, scoped)
GET|PATCH   /api/v1/properties/{id}/                      detail/update      same (no DELETE — deactivate via status)
GET|POST    /api/v1/floors/                               list (filter ?property=)/create   manage_rooms_beds
GET|PATCH|DELETE /api/v1/floors/{id}/                     detail/update/delete (only if empty)  manage_rooms_beds
GET|POST    /api/v1/rooms/                                list (filter ?floor=)/create   manage_rooms_beds
GET|PATCH|DELETE /api/v1/rooms/{id}/                      detail/update/delete (only if empty)  manage_rooms_beds
GET|POST    /api/v1/beds/                                 list (filter ?room=)/create    manage_rooms_beds
GET|PATCH|DELETE /api/v1/beds/{id}/                       detail/update/delete (blocked if occupied/reserved)  manage_rooms_beds
GET|POST    /api/v1/staff-property-assignments/           list/create        assign_staff_to_properties
DELETE      /api/v1/staff-property-assignments/{id}/      revoke assignment  assign_staff_to_properties
```

## Business rules (each maps to a test)
1. Property has no hard-delete endpoint — deactivate via `status=inactive`
   (mirrors the staff "no hard delete" pattern from Module 01).
2. Owner/Super Admin see every property in the tenant; Manager/Receptionist
   see only properties they've been explicitly assigned (PRD §6). Enforced
   both by role gate (`CanViewProperties`) and queryset scoping
   (`services.visible_property_ids`).
3. `manage_rooms_beds` (floors/rooms/beds CRUD) excludes Receptionist
   entirely, per the PRD permission matrix.
4. Creating a Floor/Room/Bed under a property the requesting Manager isn't
   assigned to is rejected (`property_not_assigned`), even though the
   property is in the same tenant and would otherwise pass RLS — RLS is
   tenant-level only, assignment-level scoping is app code.
5. A room's bed count can never exceed its `sharing_type` (its declared
   capacity) — enforced on Bed create.
6. Room `status` auto-syncs from its beds: all occupied → occupied; any
   bed available → available; otherwise → reserved. A manually-set
   `maintenance` status is left alone by sync until cleared.
7. Floors/Rooms cannot be deleted while they still have children; Beds
   cannot be deleted while `occupied` or `reserved`.
8. Only Owner (or Super Admin) can create/remove a
   `PropertyStaffAssignment`; the `staff` field is restricted to
   Manager/Receptionist accounts in the same tenant.
9. Property create/update (incl. status change) and staff-property
   assignment create/remove write audit logs (invariant 9).
10. Rack rates are `DecimalField(12,2)` throughout (invariant 5); Bed-level
    overrides fall back to the room's rate when unset
    (`Bed.rack_rate(with_food)`).
11. Tenant isolation: `properties`, `floors`, `rooms`, `beds`, and
    `property_staff_assignments` are all RLS-enforced (`test_isolation.py`
    proves it for `properties`, mirroring `apps/core/tests.py`).

## Permissions
- `manage_properties` (Super Admin, Owner): create/update properties.
- Read access to `/properties/`: Super Admin, Owner, Manager, Receptionist
  (role gate), further scoped to assigned properties for Manager/Receptionist.
- `manage_rooms_beds` (Super Admin, Owner, Manager): full CRUD on
  floors/rooms/beds, scoped to assigned properties for Manager.
- `assign_staff_to_properties` (Super Admin, Owner): manage
  `PropertyStaffAssignment` rows.

## Edge cases handled
- Manager passing a property/floor/room ID from their own tenant that they
  are *not* assigned to → 400, not 404 (the object exists and is
  tenant-visible via RLS; it's the assignment check that fails).
- Assigning a User who isn't Manager/Receptionist, or who belongs to
  another tenant → rejected (the `staff` field's queryset is scoped to
  `tenant_id` + `STAFF_ROLES`, so it surfaces as a normal "does not exist").
- Removing a `PropertyStaffAssignment` immediately revokes that Manager's
  visibility of the property (no caching — queryset is evaluated per request).
- Bed rack-rate override only affects that bed; clearing it (`null`) falls
  back to the room's rate again.

## Open questions / Decisions
- [DECISION 2026-07-03] `floors_count` / `rooms_count` / `beds_count` on
  Property, and `current_occupancy` / `bed_capacity` on Room, are computed
  in the serializer from child rows, never stored columns — the PRD calls
  them "auto-calculated," and a stored counter can drift.
- [DECISION 2026-07-03] Room/Bed `status` is a writable field (not derived
  read-only): Owner/Manager can explicitly set `maintenance`. The three
  other values (`available`/`occupied`/`reserved`) are recomputed on every
  Bed save via `Room.sync_status()`, so a manual mis-set of e.g. `occupied`
  self-corrects on the next bed change. Only `maintenance` is a true
  override and sticks until cleared.
- [DECISION 2026-07-03] `PropertyStaffAssignment` lives in `apps.properties`
  (not `apps.accounts`) since it references `Property`; this fulfills the
  Module 01 decision that deferred staff–property assignment here.
- [DECISION 2026-07-03] Property has no DELETE endpoint (deactivate only).
  Floor/Room/Bed support DELETE but only when empty of children (Bed: only
  when not occupied/reserved) — these are pre-occupancy structural fixes,
  not data-retention-sensitive like Property.
- [DECISION 2026-07-03] Plan limits on property count (invariant 10) are
  **not** enforced in this module — the Plan/cap config lives in Module 13
  (Subscription), which doesn't exist yet. Revisit when Module 13 lands.
- [DECISION 2026-07-03] Property Settings (Module 2B in the PRD — room
  transfer rent timing, late payment penalty config) are out of scope here;
  they're Module 03 per the build-order doc.
- [OPEN] PRD's "when a matching room becomes available, system suggests
  moving flagged residents" (temporary allocation) is explicitly V2 —
  irrelevant until Module 06.

## Changelog
- 2026-06-xx  Created stub.
- 2026-07-03  Built: Property/Floor/Room/Bed/PropertyStaffAssignment models
  (all RLS-enforced), property-visibility scoping service, full CRUD API,
  bed-capacity and room-status-sync business rules, staff-property
  assignment endpoints, 26 tests (isolation + business rules + permission
  scoping). Spec rewritten to as-built.
