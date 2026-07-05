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

Table: property_images              (RLS enforced)
  id                uuid PK
  tenant_id         uuid            (RLS)
  property          FK -> properties (related_name='images')
  image             ImageField      (local MEDIA_ROOT in dev, S3 when
                                     AWS_STORAGE_BUCKET_NAME is set — same
                                     storage abstraction as resident documents)
  order             positive smallint  (default 0, set to current count on
                                     upload — display order)
  created_at / updated_at

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
POST        /api/v1/properties/{id}/images/                upload one image   manage_properties (multipart, field `image`)
DELETE      /api/v1/properties/{id}/images/{image_id}/     delete one image   manage_properties
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
  **Fulfilled 2026-07-04:** Module 13 added a `check_property_limit()` call
  to `PropertyViewSet.perform_create` (fail-open when no plan is configured
  — see that module's spec).
- [DECISION 2026-07-03] Property Settings (Module 2B in the PRD — room
  transfer rent timing, late payment penalty config) are out of scope here;
  they're Module 03 per the build-order doc.
- [OPEN] PRD's "when a matching room becomes available, system suggests
  moving flagged residents" (temporary allocation) is explicitly V2 —
  irrelevant until Module 06.
- [DECISION 2026-07-05] Property photos (PRD Module 2 "list a new property
  asset") are a separate `PropertyImage` model (one row per photo, `order`
  for display sequence), not a single field on `Property` — the frontend's
  Add Property form needs to show/reorder/remove multiple photos.
  Uploaded via plain multipart POST straight to Django (`ModelViewSet`
  action + `ImageField`), matching the precedent already set by
  `Resident.aadhaar_document`/`pan_document` and `Complaint.attachment`
  — not the S3-presigned-direct-upload flow `docs/frontend-plan.md`
  aspirationally lists as a Module 04 prerequisite (that flow was never
  actually built; this module follows what's actually in the codebase).
  Storage is the existing project-wide abstraction (local `MEDIA_ROOT` in
  dev, S3 when `AWS_STORAGE_BUCKET_NAME` is set) — no new S3 code.
- [DECISION 2026-07-05] `PropertyViewSet.http_method_names` now includes
  `'delete'` (previously excluded it as the mechanism blocking hard
  delete) so the nested `images/{id}/` DELETE route can dispatch. The "no
  hard delete on Property" guarantee (invariant/decision above) is now
  enforced explicitly instead: `destroy()` is overridden to raise
  `MethodNotAllowed`. Existing test `test_property_has_no_delete_endpoint`
  still asserts 405 and passes unchanged.
- [DECISION 2026-07-05] Dev-only Django media serving was missing
  entirely (`config/urls.py` had no `static()` mapping for `MEDIA_URL`) —
  uploaded files 404'd in local dev regardless of app (this predates this
  module's changes and also affected resident documents). Added the
  standard `if settings.DEBUG: urlpatterns += static(...)` — no effect in
  prod, where S3 serves media directly.
- [DECISION 2026-07-05] The frontend `AddPropertyForm` calls Django
  directly from the browser with a JWT in `localStorage`
  (`frontend/src/lib/api.ts`), not the httpOnly-cookie BFF proxy
  `docs/frontend-plan.md` §3.1 specifies — that proxy doesn't exist yet
  anywhere in the app (no route exercises real auth before this change).
  CORS is enabled for `http://localhost:3000` in `dev.py` only. This is an
  explicit, owner-approved stopgap to unblock this form; the BFF proxy
  still needs to be built (FE-01) and this client swapped out before the
  app is exposed beyond a developer's machine. Tracked in
  `docs/frontend-plan.md` Decisions as well.

## Bugs found and fixed
- **2026-07-03 (during Module 04):** `services.can_view_property()` chained
  `.filter(pk=property_id)` onto the `visible_property_ids()` values_list
  queryset. That queryset's underlying model differs by branch — `Property`
  for Owner/Super Admin, `PropertyStaffAssignment` for Manager/Receptionist
  — so `pk` silently resolved against the *assignment's* id for Manager/
  Receptionist, not the property's. It always returned `False` for that
  branch, which happened to look correct in every Module 02 test because
  none of them asserted a Manager *succeeding* at a property they WERE
  assigned to (only the unassigned/rejected case was tested). Fixed to
  re-query `Property.objects.filter(id__in=..., pk=property_id)` so `pk`
  always resolves against `Property`. Added the missing positive-case test
  (`test_manager_can_add_floor_to_assigned_property`) here, since this is
  where the bug lived.

## Changelog
- 2026-06-xx  Created stub.
- 2026-07-03  Built: Property/Floor/Room/Bed/PropertyStaffAssignment models
  (all RLS-enforced), property-visibility scoping service, full CRUD API,
  bed-capacity and room-status-sync business rules, staff-property
  assignment endpoints, 26 tests (isolation + business rules + permission
  scoping). Spec rewritten to as-built.
- 2026-07-03  Fixed `can_view_property()` bug found while building Module 04
  (see "Bugs found and fixed"); added regression test. 27 tests.
- 2026-07-04  Module 13 added a plan-limit check (`check_property_limit`) to
  `PropertyViewSet.perform_create` — see that module's spec for the full
  enforcement design.
- 2026-07-05  Added `PropertyImage` model + `images` upload/delete actions
  (migration `0003_propertyimage`, RLS-enforced) so the Add Property form
  can attach photos — 6 new tests (43 total in this app). Wired the
  frontend Add Property form to the real API (name/type/address/city/
  state/contact_number/contact_email, matching the actual serializer —
  the mock form previously had a `pincode` field with no backend
  counterpart and no `contact_number`/`contact_email` fields at all, and
  its `property_type` options didn't match the backend enum). Added
  dev-only CORS and Django media serving (see Decisions). Regenerated
  `docs/erd.png`.
