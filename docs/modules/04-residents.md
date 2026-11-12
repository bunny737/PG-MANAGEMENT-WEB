# Module: Residents

> Keep this file in sync with the code AT ALL TIMES.
> If the code and this file disagree, this file is wrong — fix it in the same commit.

**Status:** Done
**Phase:** 1
**PRD reference:** Module 5 (Resident Management)
**Depends on:** 02
**Blocks:** 05, 11, 12, 16, 17

## Purpose
Owner/Manager capture a resident's profile (personal info, address,
emergency contact, identity documents) and track them through the PRD's
status lifecycle (Inquiry → ... → Vacated/Blacklisted). Receptionist gets
read-only lookup. This module owns the profile + status machine only —
the admission workflow (advance collection, bed allocation, contracted
rent) is Module 05/06.

## Data model (as-built)

```
Table: residents                                (RLS enforced)
  id                    uuid PK
  tenant_id             uuid              (RLS)
  property              FK -> properties  (PROTECT — never cascade-delete a resident)
  status                inquiry | reserved | active | notice_period |
                        vacated | absconded | blacklisted  (default: inquiry)

  first_name            varchar(100)      last_name  varchar(100) blank
  gender                male | female | other, blank
  date_of_birth         date, null
  phone                 varchar(15)       email      email, blank

  permanent_address     text, blank       current_address  text, blank

  emergency_contact_name      varchar(200), blank
  emergency_contact_relation  varchar(100), blank
  emergency_contact_phone     varchar(15), blank

  aadhaar_number        varchar(20), blank      aadhaar_document  file (varchar 255), null  (UUID key, kyc storage)
  pan_number             varchar(20), blank      pan_document      file (varchar 255), null  (UUID key, kyc storage)
  passport_number        varchar(30), blank
  employee_id             varchar(50), blank
  student_id               varchar(50), blank

  created_at / updated_at
```
Only `first_name` and `phone` are required — everything else is fillable
as the lead progresses (matches the Inquiry → Admission flow, where full
documents aren't available until Module 06's Admission step).

## API endpoints
```
GET|POST         /api/v1/residents/                      list/create (`ResidentListSerializer` on GET)    view_resident_profile / manage_residents
GET|PATCH        /api/v1/residents/{id}/                 detail/update (`aadhaar_document`/`pan_document` write-only)   same (status is read-only here)
GET              /api/v1/residents/{id}/documents/{field}/ short-lived signed URL `{url, expires_in, expires_at}`   view_resident_profile
PATCH            /api/v1/residents/{id}/status/          status transition                                manage_residents
```
`aadhaar_document` and `pan_document` are **write-only** on `ResidentSerializer`: list, detail, create, and update responses expose boolean presence flags (`has_aadhaar_document`, `has_pan_document`) with zero eager URL signing (`storage.url()` / IAM `signBlob`). Fresh short-lived signed URLs are issued on demand by `GET /residents/{id}/documents/{field}/` (`kyc_document_download` throttle `60/min`; returns `503` `DOCUMENT_URL_UNAVAILABLE` if signing fails).
No DELETE — a resident's history is never removed; use the status
lifecycle (`vacated`/`blacklisted`) instead.

## Business rules (each maps to a test)
1. Creating a resident defaults `status=inquiry`; profile PATCH cannot
   change `status` (it's read-only on `ResidentSerializer` by design —
   must go through `/status/`).
2. Status transitions follow the PRD Module 5 diagram, plus one owner-added
   edge (invariant 8) — `Resident.TRANSITIONS`:
   `inquiry→reserved→active→{notice_period, absconded}`,
   `notice_period→{vacated, blacklisted, active}`, `absconded→blacklisted`.
   Any other transition (including skipping stages) is rejected with
   `invalid_status_transition`. `vacated`/`blacklisted` are terminal.
   `notice_period→active` is the cancel-notice edge (owner request
   2026-10-07, Module 10); on this generic endpoint it is **rejected**
   (`open_vacate_exists`) while the resident has an open `Vacate`, so the
   withdrawal goes through `POST /vacates/{id}/cancel/` and the row is
   actually closed. Allowed here only when there is no open vacate to close.
3. Only `active` and `notice_period` residents count toward a tenant's
   plan resident limit (invariant 8) — `Resident.COUNTS_TOWARD_PLAN_LIMIT`.
   Nothing enforces the cap itself yet; that's Module 13 (no Plan model
   exists).
4. `manage_residents` (Super Admin, Owner, Manager) required to create,
   edit profile fields, or change status. `view_resident_profile` (adds
   Receptionist) is enough to list/retrieve.
5. Manager/Receptionist only see residents in properties they're assigned
   to (reuses `apps.properties.services.visible_property_ids`); creating a
   resident under an unassigned property is rejected
   (`property_not_assigned`), same pattern as Module 02's Floor/Room/Bed.
6. Resident create, status changes, and KYC document changes write metadata-only audit log entries:
   `resident.created`, `resident.status_changed`, `resident.kyc_document_uploaded`,
   `resident.kyc_document_replaced`, `resident.kyc_document_removed`, and (on signed URL issuance)
   `resident.kyc_document_url_issued`. KYC audit rows carry only `{field}` (plus magic-byte `content_type`
   on upload/replace) — never filenames, object keys, signed URLs, or Aadhaar/PAN numbers.
7. `residents` is RLS-enforced; isolation proven the same way as
   `properties`/`core`.
8. Aadhaar/PAN uploads are optional `FileField`s (`max_length=255`, UUID object keys under
   `residents/<tenant_id>/<resident_id>/<uuid><ext>`). In production they target a dedicated private hard-delete
   GCS bucket (`GS_KYC_BUCKET_NAME`, `STORAGES['kyc']` with no versioning and 0d soft delete; local filesystem
   in dev/test). `services.create_resident` / `update_resident` clean up newly written blobs best-effort if DB
   or audit writes fail, and delete replaced/cleared objects post-commit via `delete_storage_object_on_commit`.

## Permissions
- `view_resident_profile` (Super Admin, Owner, Manager, Receptionist): list/retrieve.
- `manage_residents` (Super Admin, Owner, Manager): create, profile update, status change.
- `view_activity_timeline` (Super Admin, Owner, Manager — added by Module 16):
  the `GET /residents/{id}/timeline/` action only. Deliberately excludes
  Receptionist even though they have `view_resident_profile`, since the feed
  surfaces invoice/payment figures they can't see anywhere else.
- Resident (self-service) role: no access here — PRD's "view own profile"
  is a future self-service endpoint, not this admin-facing one.

## Edge cases handled
- A Manager assigned to Property A cannot create or view a resident under
  Property B, even within the same tenant (400 on create, 404 on detail —
  same RLS-vs-assignment distinction as Module 02).
- Terminal statuses (`vacated`, `blacklisted`) reject every further
  transition, including back to `active`.
- `notice_period → blacklisted` is a valid shortcut (misconduct during
  notice) distinct from the normal `notice_period → vacated` exit.
- `notice_period → active` (cancel notice) re-checks no plan limit: both
  statuses are in `COUNTS_TOWARD_PLAN_LIMIT`, so the round trip never changes
  the tally.
- `change_status` now takes a `select_for_update(of=('self',))` row lock on the
  resident (via `residents.services.lock_resident`) so a bare status flip can't
  interleave with the Module 10 exit workflows. It re-queries by pk after
  `get_object()` rather than locking this viewset's queryset, which
  `select_related`s nullable admission/allocation joins — PostgreSQL refuses
  `FOR UPDATE` on the nullable side of an outer join.

## Open questions / Decisions
- [DECISION 2026-07-03] **Confirmed with the product owner:** Resident
  profiles do **not** get a linked login `User` account in this module.
  The PRD lists Resident as a self-service role, but neither Module 5 nor
  Module 6 (Admission) specifies when that account is provisioned.
  Deferred to whichever later module actually needs it, so an Inquiry lead
  who never converts doesn't get a dangling login account.
- [DECISION 2026-07-03] `property` is a required FK on Resident (not
  nullable) — even at the Inquiry stage a lead is inquiring about one
  specific property, and Manager/Receptionist property-assignment scoping
  needs it to filter on from day one.
- [DECISION 2026-10-20] Storage moved from S3 to Google Cloud Storage (owner decision, GCP
  hosting): `django-storages[google]`, `GS_BUCKET_NAME`, private bucket, IAM-signed 5-minute URLs
  (`apps/core/storage.py`, `GS_IAM_SIGN_BLOB`); `boto3` removed. Aadhaar/PAN upload stays gated on the
  legal review (docs/deployment.md, Phase 0). The 2026-07-03 entry below is historical.
- [DECISION 2026-07-03] Wired `STORAGES`/`AWS_*` in `config/settings/base.py`
  (conditionally — falls back to local filesystem storage when
  `AWS_STORAGE_BUCKET_NAME` is unset) so Aadhaar/PAN uploads have
  somewhere to go without requiring real AWS credentials in dev/test.
  `boto3`/`django-storages[s3]` were already in requirements from project
  bootstrap; this just activates them per the locked "Storage: AWS S3"
  stack decision. Fill in `.env` to switch a real environment to S3.
- [DECISION 2026-07-03] Passport/Employee ID/Student ID are number-only
  fields (no upload) — the PRD only says "+ Upload" for Aadhaar and PAN.
- [DECISION 2026-07-03] Document-completeness gating (e.g. "Aadhaar+PAN
  required before Active") is deliberately NOT enforced here — that's
  Module 05 (Admissions)'s "documents, billing setup" step to own.
- [DECISION 2026-11-01] **Resident self-service is Module 26.** A resident record still has no login of its own: the
  PG owns the record and it works without the app. A person creates their own app account and is linked to the
  record by accepting a staff invite or by staff approving a join-code request (`docs/modules/26-resident-identity.md`).
  The self-service views ("view own profile", "view own invoices") are Module 26b.
- [DECISION 2026-07-04] Module 13 added a plan-limit check
  (`check_resident_limit`) to `change_status` — but only when the target
  status newly counts toward the plan limit (`Reserved → Active`,
  `Vacated`-adjacent edge cases) and the resident wasn't already counted;
  `Active ↔ Notice Period` never re-checks since both already count. This
  closes the "bare status flip bypasses Admission's own check" gap called
  out below, specifically for the plan-limit case (judged consequential
  enough to guard, unlike other workflow gaps left as accepted debt).
- [DECISION 2026-10-11] Receptionist resident financial field carve-out:
  Receptionist holds `view_resident_profile` so front-desk staff can look up
  residents, verify identity, and check unit/bed allocations, but
  `ResidentSerializer` previously exposed `contracted_rent`, `billing_mode`,
  `security_deposit_amount`, `advance_amount`, and `advance_refundable`.
  To prevent data disclosure while keeping a single `GET /residents/` API,
  `ResidentSerializer.__init__` pops these five fields dynamically whenever
  the requesting user lacks `manage_residents` (`permissions_for(user.role)`).
  This prevents financial terms from reaching the front desk even if the
  frontend tab is hidden.
- [DECISION 2026-10-21] **Aadhaar/PAN upload launch gate.** `KYC_UPLOADS_ENABLED` (default `True` in dev,
  `False` in `config/settings/prod.py`; set `KYC_UPLOADS_ENABLED=true` on the API service once legal signs
  off, docs/deployment.md §9) refuses a NEW `aadhaar_document` / `pan_document` file on both create and
  update with a 400 on that field (`kyc_uploads_disabled`). Gated per field in `ResidentSerializer`, not in
  the view, so every write path is covered. **Clearing** a stored document (`null`) is always allowed
  (data minimisation), and **stored documents stay readable** via their signed URLs, so an owner can still
  see and delete what is already on file. When uploads are on, each file is checked with the shared
  `apps/core/uploads.py` (`sniff_upload`: real type from the magic bytes, at most `KYC_DOCUMENT_MAX_BYTES`,
  default 5 MB; codes `document_type_not_allowed` / `document_too_large`). **Only JPEG/PNG/PDF are
  accepted for KYC** — the approved set (plan rev 2); `sniff_upload` takes an `allowed_types` argument so
  WebP (which `apps/expenses` does accept, pre-existing on `dev`) isn't silently let through here too. The
  expenses attachment check was refactored onto the same utility (its `attachment_*` codes are unchanged),
  so residents do not import from expenses. `GET /auth/me/` exposes `kyc_uploads_enabled`; the web
  resident profile hides the upload controls (and says why) when it is false or absent. Tests:
  `apps/residents/tests/test_kyc_gate.py`, `apps/core/test_uploads.py`.
- [DECISION 2026-10-22] **Clearing or replacing a KYC file deletes the old object from storage, not just
  the database reference.** `FileField` never does this on its own — repointing it just orphans the
  previous object in GCS/local storage, which defeats the clearing path's data-minimisation purpose.
  `ResidentSerializer.update()` captures the prior `(storage, name)` for any KYC field present in
  `validated_data` before `super().update()` repoints it, then deletes the old object with
  `transaction.on_commit()` once the row update has actually committed — mirrors
  `apps/expenses/services.py`'s `_delete_file_on_commit`. A failed update (e.g. a rejected replacement)
  never reaches the deletion, so the still-referenced file is never orphan-deleted. Tests assert the file
  is gone from storage after clearing/replacing, still there after an invalid replacement, and still there
  until the transaction actually commits.

## Changelog
- `2026-11-12` (follow-up hardening):
  - `services.update_resident` now locks the `Resident` row (`lock_resident`, `select_for_update(of=('self',))`) inside `transaction.atomic()` before reading the prior object key or writing replacement blobs, preventing concurrent replacement races from orphaning blobs (`tests/test_kyc_concurrency.py`).
  - Added `manage.py backfill_kyc_documents` (idempotent cross-bucket copy with `--dry-run` and `--delete-source`) and `manage.py check_kyc_storage` (verifies `$KYC_BUCKET` existence, hard-delete settings, UBLA/PAP, IAM object perms, live V4 URL signing, and 0 unmigrated docs), wired as `pglive-backfill-kyc` and `pglive-check-kyc` in `infra/30-services.sh` / `infra/deploy.sh` (`tests/test_kyc_commands.py`).
  - Frontend download handler (`ResidentProfile.tsx`) opens a blank tab synchronously (`window.open("", "_blank")` + `popup.opener = null`) and navigates it after URL issuance (same-tab fallback if blocked; closes blank tab on error) so browsers do not popup-block async signed URL downloads.
  - Infra: `infra/10-foundation.sh` idempotently revokes legacy `sa-worker` `TokenCreator` bindings; `infra/20-data.sh` grants `pglive.bucketMetadataReader` (`storage.buckets.get`) on `$KYC_BUCKET` to `sa-api`; `infra/deploy.sh` + `infra/worker/{deploy,create-vm}.sh` forward custom `MEDIA_BUCKET`/`KYC_BUCKET` overrides to the worker VM.
- 2026-11-12  **GCS KYC rollout (Gate A1 + Gate B1).** Switched KYC uploads to dedicated hard-delete
  `STORAGES['kyc']` (`GS_KYC_BUCKET_NAME`, no versioning, 0d soft delete) with UUID object keys (`max_length=255`);
  split `ResidentListSerializer` vs `ResidentSerializer`, made `aadhaar_document`/`pan_document` write-only and
  exposed `has_aadhaar_document`/`has_pan_document`; added `GET /residents/{id}/documents/{field}/`
  (`503 DOCUMENT_URL_UNAVAILABLE`, `60/min` throttle, mandatory `resident.kyc_document_url_issued` audit);
  added `perform_create`/`perform_update` service orchestration (`resident.kyc_document_{uploaded,replaced,removed}`
  metadata-only audits + best-effort orphan cleanup + hardened `delete_storage_object_on_commit`); updated
  web UI with tolerant client validation, on-demand Download, and confirmed Remove.
- 2026-10-22  KYC file replace/clear now deletes the orphaned storage object; KYC uploads restricted to
  JPEG/PNG/PDF (WebP no longer accepted here) — see Decisions.
- 2026-10-21  KYC upload launch gate + shared upload validation (see Decisions); `/auth/me/` gains
  `kyc_uploads_enabled`.
- 2026-10-20  Storage S3 → GCS (signed URLs via `apps.core.storage`); see Decisions.
- 2026-06-xx  Created stub.
- 2026-07-03  Built: `Resident` model (RLS) with exact PRD status-transition
  graph, profile CRUD + dedicated status-change endpoint, permission
  scoping reusing Module 02's property-assignment service, audit logging,
  conditional S3/local document storage, 23 tests (isolation + transitions
  + permission scoping + document upload). Found and fixed a property-
  visibility bug in Module 02's `services.py` along the way (see that
  module's "Bugs found and fixed"). Spec rewritten to as-built.
- 2026-07-04  Module 13 added a plan-limit check to `change_status` (see
  Decisions) — no other change to the status-transition endpoint.
- 2026-07-04  Module 16 added a `timeline` action + `view_activity_timeline`
  permission to `ResidentViewSet` (see Permissions) — no other change to
  this viewset.
- 2026-10-04  `ResidentSerializer` gained read-only admission/allocation
  fields for the mobile app: `contracted_rent` (from the current Allocation, so
  it follows a permanent transfer), `food_preference`, `billing_mode`,
  `joining_date`, `security_deposit_amount`, `advance_amount`,
  `advance_refundable`, `room_number`, `bed_number`. All null for a resident
  with no admission. The queryset `select_related`s admission/allocation so
  the list adds no per-row queries.
- 2026-10-07  Module 10 added the `notice_period -> active` edge (cancel
  notice, owner request), a row lock on `change_status` via
  `residents.services.lock_resident`, and a guard rejecting that transition on
  this generic endpoint while the resident has an open `Vacate` — see that
  module's 2026-10-07 update for the reasoning and the lock order, which
  admission (Module 05) now follows too.
- 2026-10-12  Per-staff module access (Module 01 `[DECISION 2026-10-12]`): `ResidentSerializer`
  hides `contracted_rent`/`billing_mode` without `view_finance`, and the deposit figures
  (`security_deposit_amount`, `advance_amount`, `advance_refundable`) without `view_finance` or
  `manage_deposits` (previously both groups keyed on `manage_residents`; role defaults unchanged).
  The `timeline` action now requires `view_resident_profile` **and** `view_activity_timeline`.
- 2026-10-16  UX roadmap D6: `GET /residents/{id}/` (detail only) adds a
  `finance` block — `apps/residents/finance.py:resident_finance()` — covering
  the property-timezone current month's invoice(s), `outstanding_total`,
  `overdue_total`, `prior_outstanding` and `last_payment_date`. Needs
  `view_finance`; otherwise `finance` is `null` and `"finance"` is listed in
  the response's top-level `redacted`. Full shape and the card-state mapping
  are documented with Module 21 (the single home for the roadmap's
  authorization model and response shapes). Test: `test_resident_finance.py`.
- 2026-10-17  Web-client follow-up (S0b): the detail response's `finance` +
  `redacted` fields build a plain dict by hand (as above), so `/api/schema/`
  described them as untyped. `retrieve()` now carries
  `@extend_schema(responses=ResidentDetailResponseSerializer)` — a
  schema-only subclass of `ResidentSerializer` adding those two fields, in
  the new `apps/residents/schema.py` (never instantiated for a real
  response). See Module 21's 2026-10-17 decision for the full list and the
  test that guards it.
