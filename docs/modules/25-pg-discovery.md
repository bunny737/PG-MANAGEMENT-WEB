# Module: PG Discovery ("Find a PG")

> Keep this file in sync with the code AT ALL TIMES.
> If the code and this file disagree, this file is wrong — fix it in the same commit.

**Status:** Not Started — design agreed 2026-10-31, recorded here so it survives the planning session
**Phase:** 3 (owner request 2026-10-31 — not in PRD v2)
**Depends on:** 01, 02, 03, 05, 13, 14, 18, 22, and **26a** (its contact gate needs seeker accounts — done)
**App:** new `apps.listings`

## Purpose
Anyone can **search nearby PGs without logging in**. To **see contact details or send an inquiry** they must be signed
in with a **verified resident-pool account** (Module 26). An inquiry becomes a lead in the owner's Admissions.
Listing is free, opt-in per property, off by default.

## Core design (decided)
**Public search never reads tenant tables.** RLS lets a row through only for its own tenant or a super admin, and an
anonymous request must never set the super-admin GUC. So:

- `PropertyListing` — tenant table, one per property **created in the same transaction as the property** (backfilled
  for existing ones): `is_published` (default false), `description`, `show_phone`, `show_whatsapp`, `whatsapp_number`,
  `show_price`, `show_vacancy`, `hidden_by_platform`, `hidden_reason`.
- `PublicListing` — a snapshot of public-safe fields, the **only** table anonymous search reads. **No phone numbers**
  (only `has_phone` / `has_whatsapp` booleans). Price columns are NULL when `show_price` is off, `vacant_beds` NULL when
  `show_vacancy` is off. Composite FK `(property_id, tenant_id)` → `properties(id, tenant_id)`.
  **Four per-command RLS policies:** SELECT `USING (true)`; INSERT `WITH CHECK (tenant OR super)`; UPDATE
  `USING (tenant OR super) WITH CHECK (same)`; DELETE `USING (tenant OR super)`. (A single `FOR ALL USING (true)`
  would let anyone delete other tenants' rows.) Use `apps.core.rls`-style helpers.
- `ListingInquiry` — tenant table; SELECT also admits `seeker_user_id = app.user_id` (SELECT-only; same helper as
  Module 26). `seeker_user` is **SET_NULL** on account deletion (the lead belongs to the PG). Staff serializers never
  expose it.
- `ListingContactReveal` — tenant table; `listing` FK → the persistent **`PropertyListing`** (not the deletable
  snapshot); `UNIQUE(seeker_user, listing, reveal_day)`.
- `ContactRevealQuota` — `(user, day)` unique with a counter; RLS keyed on `user_id = app.user_id`. Enforced with one
  atomic `INSERT … ON CONFLICT … DO UPDATE … WHERE count < :cap RETURNING count`; day = Asia/Kolkata.

## Snapshot consistency and the locking protocol
- **Withdrawals are synchronous**, in the same transaction as the change, and never depend on Celery: unpublish,
  platform hide, property deactivation, subscription suspension/cancellation and tenant/property deletion **delete the
  snapshot row**; turning a `show_*` flag off NULLs the price/vacancy columns or sets `has_*` false.
- **Enrichment is asynchronous** (`on_commit` → Celery `refresh_public_listing`): lock the `PropertyListing`, read
  **current** source rows, upsert if `is_publicly_visible()`, else delete. A refresh blocked behind a withdrawal
  re-reads after the lock, so it cannot resurrect the row. Retries with backoff; a nightly beat rebuilds every visible
  listing and deletes orphans.
- **One visibility function**, `is_publicly_visible()`: published, not hidden, property active, tenant not blocked.
- **Reveal and inquiry** both lock the listing and re-run it (plus the current `show_*` toggles) before reading or
  writing. A reveal is one transaction: lock → recheck → existing reveal today? (no quota) → quota increment → insert.
- **Gate for listing-set changes:** property creation, publication, suspension, cancellation, reactivation and tenant
  purge lock the tenant's **`Subscription` row first**, then the listings in `property_id` order. So a property cannot
  commit and publish while a suspension is in flight.

> **OPEN — reconcile before building.** Required order in the agreed design is **Subscription → PropertyListing (by
> id) → Public/Inquiry/Reveal → Resident → ResidentInvite/Access/LinkRequest**. The *existing* exit workflows lock
> **Resident → Vacate → Bed → Subscription** (`residents.services.lock_resident`, and `check_resident_limit` takes the
> Subscription last). Those two orders are not compatible for a path that touches both a listing and a resident
> (inquiry conversion). Audit every `select_for_update` site (`subscriptions/services.py`, `residents/services.py`,
> `accounts/deletion.py`, `billing/services.py`, `notices/services.py`) and the implicit `FOR KEY SHARE` locks FKs take,
> then either keep conversion out of the Subscription lock set or change the order, and record the result here.

## Calculation rules
- **Price from:** minimum effective rack rate (bed override → room rate) over beds not under maintenance, per food
  option. This is advertising, not billing; invariant 2 is untouched.
- **Vacancy:** beds `available` in rooms not under maintenance.
- **`food` filter** picks the price column; without it, the lower non-null price is shown.
- **`max_price`** matches visible prices only (NULL excluded); price ordering puts NULLs last, so a hidden price can't
  be inferred.
- **Distance:** bounding box on indexed lat/lng, then haversine (float is fine; not money).
- **Pagination:** keyset on (sort key, id). Guarantee: no duplicates or skips for listings whose sort key does not
  change between requests; a listing whose price/vacancy/position changes may move between pages. Default and max
  radius and page size live in `PlatformConfig` (invariant 10).

## Endpoints (planned)
```
GET/PATCH /properties/{id}/listing/                edit_properties   publish needs a pin, ≥1 image, ≥1 room; audited
GET  /public/listings/ , /public/listings/{id}/    anonymous, throttled; signed image URLs; no GUC set
GET  /listings/{id}/contact/                       verified resident account (401 / 403 otherwise)   quota + reveal row
POST /listings/{id}/inquiries/                     same gate; honeypot + size cap; tenant from the snapshot only
POST /listings/{id}/link-request/                  calls Module 26's request_residency_link for the listing's property
GET  /me/inquiries/                                the person's own inquiries
GET/PATCH /listing-inquiries/ , POST …/{id}/convert/   manage_admissions; display-only possible_matches
```
`convert` is atomic and idempotent (returns the existing resident on retry); it creates an Inquiry-status `Resident`,
or links an explicit `resident_id` that must belong to the inquiry's property and be visible to the staff member.

## Hooks
Module 13 (suspend/cancel/reactivate follow the protocol), Module 14 (`listing_inquiry_received`, en + te), Module 22
(`DISPOSITION` rows for all five tables: `PropertyListing`, `PublicListing`, `ListingInquiry`, `ListingContactReveal`,
`ContactRevealQuota`), Django admin (hide/unhide = a synchronous withdrawal).

## Tests required
Withdrawal with Celery forced to fail; concurrent refresh vs unpublish / suspension / deactivation / contact hiding;
the first-publication race (suspension holds the subscription → new property blocks → publication refuses → no snapshot
survives); reveal/inquiry vs withdrawal (denied when the withdrawal wins, no visibility after it commits); quota never
exceeded across listings, repeat reveal doesn't count (also after republish), a failed reveal leaves the quota
unchanged; hidden price/vacancy not inferable by filter or order; anonymous responses never contain a number; raw-SQL
policy tests (anonymous can't insert/update/delete; tenant A can't update/delete tenant B's snapshot; mismatched
property/tenant fails the FK; the seeker clause is SELECT-only).

## Decisions
- [DECISION 2026-10-31] Search is public (Flutter app and a `noindex` web `/find-pg`); contact and inquiry need a
  logged-in, email-verified resident account; listing is free and opt-in per property.
- [DECISION 2026-10-31] For Modules 25/26 **Flutter ships before the web resident portal** (a deviation from the
  Web/PWA-first rule, recorded in docs/frontend-plan.md).

## Changelog
- 2026-11-01  Spec recorded from the agreed design; nothing built.
