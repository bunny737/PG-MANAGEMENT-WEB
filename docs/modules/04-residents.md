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

  aadhaar_number        varchar(20), blank      aadhaar_document  file, null
  pan_number             varchar(20), blank      pan_document      file, null
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
GET|POST         /api/v1/residents/            list/create              view_resident_profile (read) / manage_residents (write)
GET|PATCH        /api/v1/residents/{id}/       detail/update profile    same (status is read-only here)
PATCH             /api/v1/residents/{id}/status/  status transition     manage_residents
```
No DELETE — a resident's history is never removed; use the status
lifecycle (`vacated`/`blacklisted`) instead.

## Business rules (each maps to a test)
1. Creating a resident defaults `status=inquiry`; profile PATCH cannot
   change `status` (it's read-only on `ResidentSerializer` by design —
   must go through `/status/`).
2. Status transitions follow the PRD Module 5 diagram exactly
   (invariant 8) — `Resident.TRANSITIONS`:
   `inquiry→reserved→active→{notice_period, absconded}`,
   `notice_period→{vacated, blacklisted}`, `absconded→blacklisted`.
   Any other transition (including skipping stages) is rejected with
   `invalid_status_transition`. `vacated`/`blacklisted` are terminal.
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
6. Resident create and every status change write an audit log
   (`resident.created`, `resident.status_changed` with before/after).
7. `residents` is RLS-enforced; isolation proven the same way as
   `properties`/`core`.
8. Aadhaar/PAN uploads are optional `FileField`s; storage backend is S3 in
   production, local filesystem in dev/test (see Decisions) — no field is
   required to exist for a resident to be created.

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
- [OPEN] No endpoint yet for the PRD's resident self-service views ("view
  own profile", "view own invoices") — that needs the login-account
  question above resolved first, likely in Module 05 or a dedicated step.
- [DECISION 2026-07-04] Module 13 added a plan-limit check
  (`check_resident_limit`) to `change_status` — but only when the target
  status newly counts toward the plan limit (`Reserved → Active`,
  `Vacated`-adjacent edge cases) and the resident wasn't already counted;
  `Active ↔ Notice Period` never re-checks since both already count. This
  closes the "bare status flip bypasses Admission's own check" gap called
  out below, specifically for the plan-limit case (judged consequential
  enough to guard, unlike other workflow gaps left as accepted debt).

## Changelog
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
