# Module: PG Features

> Keep this file in sync with the code AT ALL TIMES.
> If the code and this file disagree, this file is wrong — fix it in the same commit.

**Status:** Done
**Phase:** 3
**PRD reference:** none — owner request 2026-10-06 (not in PRD v2). Closest anchor is
Module 2 (Property Management).
**Depends on:** 02
**Blocks:** none

## Purpose
Lets an Owner or Manager record what a PG offers its residents (Wi-Fi, power
backup, lift, CCTV, laundry, parking, ...). They tick from a platform-curated
list while creating the PG (optional) or later on the PG's Features page; a
feature that isn't listed can be typed in and is then available on all of that
tenant's PGs. A PG with several buildings can add features for one building or
mark an inherited feature as not available there.

"Feature" here means a PG facility. It is unrelated to subscription "plan
features" (PRD prose only — there is no such model).

## Data model (as-built)
All three models live in `apps.properties`.

```
Table: feature_catalog   (global — NO RLS, platform-seeded, like plans)
  id              uuid PK
  code            slug, unique        stable identifier, never renamed
  category        rooms | food | housekeeping | connectivity | utilities | safety |
                  recreation | parking | services | accessibility | policies
  display_order   smallint
  is_popular      bool                shortlist shown first in the create-PG form
  is_active       bool                retire with False; rows are never deleted
  created_at / updated_at

Table: tenant_features   (RLS enforced)
  id              uuid PK
  tenant_id       uuid (RLS)
  label           varchar(60)         exactly as the owner typed it
  slug            varchar(255)        feature_catalog.normalise(label) — dedupe key
  is_active       bool
  created_at / updated_at
  UNIQUE (tenant_id, slug)

Table: property_features   (RLS enforced)
  id              uuid PK
  tenant_id       uuid (RLS)
  property        FK → properties (CASCADE)
  building        FK → buildings (CASCADE), NULL = whole PG
  catalog_feature FK → feature_catalog (PROTECT), nullable
  tenant_feature  FK → tenant_features (CASCADE), nullable
  is_available    bool, default True  False only on a building row = "not in this building"
  is_paid         bool, default False informational: Included vs Extra cost
  created_at / updated_at
  CHECK  exactly one of catalog_feature / tenant_feature is set
  CHECK  is_available = True OR building IS NOT NULL
  UNIQUE (property, building, catalog_feature, tenant_feature) NULLS NOT DISTINCT
```

Display labels for catalogue codes are not stored: they are `gettext_lazy`
strings in `apps/properties/feature_catalog.py` (`FEATURE_LABELS`), keyed by
code. The 72 seeded codes are listed in
`migrations/0007_seed_feature_catalog.py`.

## API endpoints
```
GET    /api/v1/feature-catalog/              platform catalogue (?category=, ?is_active=)   any authenticated user
GET    /api/v1/feature-catalog/{id}/         one catalogue row                              any authenticated user
GET    /api/v1/tenant-features/              the tenant's own features                      view_property_features
POST   /api/v1/tenant-features/              add one — 201 created, 200 already existed     manage_property_features
PATCH  /api/v1/tenant-features/{id}/         rename / set is_active                         manage_property_features
DELETE /api/v1/tenant-features/{id}/         delete (400 feature_in_use while assigned)     manage_property_features
GET    /api/v1/properties/{id}/features/     see below                                      view_property_features
POST   /api/v1/properties/{id}/features/     replace the whole set at one scope             manage_property_features
```

`GET /properties/{id}/features/`
- no query: every row of the PG, each at its own scope (`source` =
  `property` | `building`, `building` = id or null). `excluded` lists every
  building's "not in this building" rows.
- `?building=<id>`: the effective set for that building — property rows merged
  with that building's rows by feature identity, the building row winning.
  Inherited features the building has marked unavailable are left out of
  `items` and returned in `excluded`.
- `derived` = `{sharing_types, room_categories}` read from the rooms in scope
  (all rooms of the PG, or only that building's).

Response: `{property, building, items[], excluded[], derived}`; each item is
`{id, source, building, feature_type: catalog|custom, code, tenant_feature,
label, category, category_label, is_paid, is_active}`.

`POST /properties/{id}/features/` — PUT semantics on POST (this app does not
route PUT). Body:
```
{"building": null | "<uuid>",
 "items":    [{"code": "wifi", "is_paid": false}, {"tenant_feature": "<uuid>", "is_paid": true}],
 "excluded": [{"code": "lift"}]}        # building scope only
```
Replaces the set at exactly that scope; other scopes are untouched. Returns
the same shape as the matching GET.

Error codes (in `code`, upper-cased by the API exception handler):
`building_not_in_property`, `feature_source_ambiguous`,
`feature_source_required`, `unknown_feature`, `duplicate_feature`,
`too_many_features`, `suppression_requires_building`, `nothing_to_suppress`,
`feature_not_active`, `feature_label_required`, `feature_label_too_long`,
`feature_in_global_catalog` (body also carries `catalog_code`),
`feature_already_exists`, `feature_in_use`.

## Business rules (each maps to a test)
Tests: `apps/properties/tests/test_pg_features.py` (numbers match test names)
and `tests/test_isolation.py`.

Catalogue
1. The catalogue lists in `(category, display_order)` order.
2. The catalogue is read-only over the API (405 on writes).
3. A retired (`is_active=False`) row is hidden from tenants, visible to Super Admin.
4. Every seeded code has a `FEATURE_LABELS` entry and vice versa.
5. `label` and `category_label` follow `Accept-Language` (en / te).

Replace
6. A replace removes anything not in the payload.
7. Property scope and each building scope are replaced independently.
8. A building view tags inherited rows `source=property`, its own `source=building`.
9. A feature at both scopes appears once, with the building's `is_paid`.
10. The unfiltered view returns every row at its own scope.
11. A building of another property → 400 `building_not_in_property`.
12. Each item needs exactly one of `code` / `tenant_feature`; unknown → `unknown_feature`.
13. The DB itself rejects a row with both or neither feature FK.
14. The same feature twice in one payload → `duplicate_feature`.
15. Re-posting an identical set changes no rows and writes no audit entry.
16. `items: []` clears the scope.
17. More than 200 features in one payload → `too_many_features`.
18. `is_paid` never creates or changes anything in billing.

Building override
19. A building can mark an inherited feature unavailable; it moves to `excluded`.
20. Dropping that mark restores inheritance.
21. Marking unavailable is building-only (`suppression_requires_building`,
    enforced by a DB CHECK too) and only for a feature the PG offers
    (`nothing_to_suppress`).
22. An "unavailable" row is never paid, and is deleted when the PG stops
    offering that feature.

Concurrency
23. Two concurrent replaces on one PG leave one complete set, never a mix.

Retirement
24. A feature retired after assignment is still returned, with `is_active: false`.
25. A save that still includes it keeps it.
26. A retired feature cannot be newly assigned (`feature_not_active`).
27. A catalogue row in use cannot be deleted (`PROTECT`).

Audit
28. Changing only Included ↔ Extra cost writes an audit entry.
29. `property_features.updated` records the scope and, per feature,
    `{type, key, is_paid, is_available}` before and after.

Custom features
30. A custom feature can be used on any PG of the tenant.
31. The same name in other casing/spacing returns the existing feature (200).
32. Distinct Telugu names stay distinct.
33. A name matching a catalogue code, English label or alias is rejected with
    `feature_in_global_catalog` + `catalog_code`, whatever the request locale.
34. `normalise()` matches `tests/fixtures/feature_normalisation.json`.
35. Renaming onto a catalogue feature is rejected.
36. Renaming onto another of the tenant's features is rejected.
37. A rename is audited (`tenant_feature.updated`) and shows wherever assigned.
38. Another tenant's custom feature id → 400 `unknown_feature`.
39. A custom feature in use cannot be deleted (`feature_in_use`).

Derived facts, lifecycle, access
40. `derived` lists the sharing types and room categories in use; empty with no rooms.
41. Sharing types above 4 are reported (rooms go up to 8-sharing).
42. With `?building=`, `derived` covers only that building's rooms.
43. Deleting a building removes its rows only; deleting the PG removes all.
44. Owner/Manager write; Receptionist read-only; Resident no access.
45. A Manager not assigned to the PG gets 404.
46. That 404 comes before any feature validation, so nothing leaks.
47. `PropertyFeature.clean()` rejects a building from another property.

Isolation: the 4-assertion RLS proof for `tenant_features` and
`property_features`, plus a check that `feature_catalog` is readable with no
tenant context.

## Permissions
| Code | Roles |
|---|---|
| `view_property_features` | Super Admin, Owner, Manager, Receptionist |
| `manage_property_features` | Super Admin, Owner, Manager |

Manager and Receptionist are further limited to PGs they are assigned to
(`services.visible_property_ids`). The custom-feature list is tenant-wide.
The catalogue itself changes only through Django admin (reorder, shortlist,
retire) and seed migrations (add).

## Edge cases handled
- Indic text: the dedupe key keeps combining marks, so Telugu/Hindi names
  that differ only by vowel signs do not collide.
- Type-to-add is idempotent (double-click, stale client list, DB race).
- A retired feature is never silently dropped by a save from a picker that no
  longer lists it; the UI shows it under "No longer offered" with Remove.
- A building keeps no "unavailable" mark for a feature the PG has dropped.
- Concurrent saves are serialised per PG by a row lock on the property.
- Creating a PG and saving its features are two requests; if the second
  fails the PG still exists and the selection is kept in `sessionStorage`
  (cleared on logout) for the Features page to pick up.

## Open questions / Decisions
- [DECISION 2026-10-06] **What is and isn't a feature.** The owner's candidate
  list was triaged against the schema:
  - *Already modelled — shown read-only as `derived`, never stored again:*
    sharing type (`Room.sharing_type`, 1–8) and AC / Non-AC (`Room.category`).
  - *Money and terms — not features:* "X charged separately" is the `is_paid`
    flag on feature X; per-unit electricity, guest and damage charges are
    invoice line items (Module 08); security deposit and notice period are
    Module 10; monthly plans are the billing cycle.
  - *Is a feature after all:* food/mess. Both rack rates are mandatory on
    every room, so "this PG serves food" is not derivable.
  - *Kept by request:* a `policies` category (no curfew, flexible entry
    timings, short-term stay) — positive yes/no claims only; the UI hides the
    Included/Extra cost choice for it.
  - *Excluded:* location facts (metro nearby), our own product features.
- [DECISION 2026-10-06] Scope is the PG, with an optional per-building
  override that can add, re-price, or mark unavailable. Suppression is a row
  with `is_available=False`, legal only on a building (DB CHECK). The UI shows
  the scope selector only when a PG has more than one building.
- [DECISION 2026-10-06] Custom features are a per-tenant table, not free text
  on the assignment, so one typed feature is reusable and renameable in one
  place. Custom labels are owner data and are not translated.
- [DECISION 2026-10-06] `is_paid` is a bare boolean with no amount and is
  never read by billing. Chargeable add-ons stay on the reserved
  `Admission.addons` path (invariant 6).
- [DECISION 2026-10-06] The catalogue stores codes; labels are `gettext_lazy`
  strings in code so `makemessages` sees them. Consequently a catalogue row
  cannot be added from Django admin (it would have no translatable label) —
  adding a feature is a seed migration plus a `FEATURE_LABELS` entry.
- [DECISION 2026-10-06] The frontend renders the API's translated `label`
  rather than mirroring 72 labels in three locale files.
- [DECISION 2026-10-06] Duplicate detection is locale-independent: it matches
  the code, the English label and `FEATURE_ALIASES`, never a translation, so
  the same text is not accepted in one language and rejected in another.
- [DECISION 2026-10-06] The dedupe key is `normalise()` (NFKC, lowercase, keep
  letters + marks + numbers), not `slugify()`. `slugify(allow_unicode=True)`
  strips Indic vowel signs: "కిటికీ" and "కటక" both become "కటక".
- [DECISION 2026-10-06] All writes go through `feature_services`. The DB can't
  check that a building belongs to the property or that every FK shares the
  tenant, so `PropertyFeature` is read-only in Django admin and
  `TenantFeature` edits there call the same service — a deliberate departure
  from this app's bare `admin.site.register`.
- [DECISION 2026-10-06] The bulk payload accepts only `code` or
  `tenant_feature` per item. New custom features are created first through
  `/tenant-features/`.
- [DECISION 2026-10-06] Assignments are a nested action on `PropertyViewSet`
  (inherits assignment scoping); the two catalogues are standalone viewsets.
  There is no `/buildings/{id}/features/` — `?building=` covers it.
- [DECISION 2026-10-06] The unique constraint relies on `NULLS NOT DISTINCT`
  (Django ≥ 5.0, Postgres ≥ 15). Fallback if that floor ever moves: four
  partial unique constraints split on `building IS NULL` and on which feature
  FK is set.
- [DECISION 2026-10-06] Daily and weekly room cleaning are not mutually
  exclusive in the DB or the UI.
- [DECISION 2026-10-06] Features are not part of Module 17 exports.
- [OPEN] Lock-in period has no model anywhere; it is an agreement term with a
  duration, not a feature.
- [OPEN] "Electricity included in rent" — no property-level model exists and
  it is a billing promise. Owners can add it as a custom feature meanwhile.
- [OPEN] A curfew with a time needs a value field (future house-rules work).
- [OPEN] Attached / common bathroom are really room attributes; if `Room`
  gains such a field these two codes should be retired and derived instead.
- [OPEN] Resident-facing read access (no resident login exists yet).
- [OPEN] Merging a tenant's custom feature into a later-added platform code.
- [OPEN] Telugu wording for the catalogue was written without a native review.
- [OPEN] The frontend has no test runner, so `featureText.test.ts` follows the
  existing un-run pattern; parity with the backend fixture was checked by hand
  in Node.
- [OPEN] The unsaved-changes prompt covers browser unload, the scope selector
  and the page's own links, not the app sidebar.

## Changelog
- 2026-10-06  Built: three models (migrations `0006`, `0007` seed of 72
  codes; RLS on the two tenant tables), `feature_catalog.py`,
  `feature_services.py`, catalogue / tenant-feature viewsets, nested
  `/properties/{id}/features/`, two permission codes, hardened admin, Telugu
  catalogue translations, 45 tests + 9 isolation tests. Frontend:
  `FeaturePicker`, Features page (`/properties/[id]/features`), optional
  section in the Add Property form, `usePermissions()`, removal of the mock
  room `amenities`. Regenerated `docs/erd.png`.
