# Module: Resident Identity & App Access

> Keep this file in sync with the code AT ALL TIMES.
> If the code and this file disagree, this file is wrong — fix it in the same commit.

**Status:** In Progress — **26a done** (identity, request context, link lifecycle, deletion); **26b not started** (the `/me/*` read endpoints, complaints, visitor requests)
**Phase:** 3 (owner request 2026-10-31 — not in PRD v2; PRD §9 "Resident App")
**PRD reference:** PRD §9 Resident App (view profile/billing/receipts, complaints, visitor requests, notices)
**Depends on:** 01 (users, JWT, OTP), 04 (residents), 10 (exit statuses), 14 (notifications), 15 (audit), 22 (account deletion). 26b also: 08, 09, 11, 12, 13, 19, 24.
**Blocks:** 25 (PG Discovery — its contact gate needs seeker accounts), the Flutter resident screens, the web resident portal (FE-R1).
**Apps:** `apps.accounts` (pools, `resident_auth.py`), `apps.residents` (`access.py`, `access_models.py`, `access_views.py`, `tasks.py`), `apps.properties` (`join_codes.py`), `apps.core` (tenancy GUC, RLS helper, permissions).

## Purpose
The resident app needs residents to be able to sign in. This module gives a person their **own app account**
and a safe way to **link** it to the record a PG keeps for them — without ever making the PG's records depend
on a login.

Three separate things:

| Thing | Owned by | Needs a login? |
|---|---|---|
| **Resident** — the record: admission, allocation, billing, payments | the PG | **No.** Works exactly as before, with or without the app |
| **App account** — a resident-pool `User` the person creates themselves | the person | — |
| **Link** (`ResidentAccess`) — "this account may see this record" | created only by an accepted **invite** or an approved **link request** | — |

Staff actions never create a `User`. A resident with no email still gets full service from the PG; they just
have no app until they sign up and ask to be linked. No placeholder emails, no shared accounts.

## Isolation model (read this first)
- **Database RLS isolates tenants.** Selecting a residency sets `app.tenant_id`, which admits **every** row of that
  PG — including other residents'.
- **The application isolates residents from each other.** Every resident endpoint must filter through the selected
  link's `resident_id` (PDFs, comments, uploads and nested resources included). Separate serializers are not
  isolation. `ResidencyScopedAPIView` hands each handler `self.resident`; Module 26b tests every endpoint with two
  residents in one PG.
- A resident account has **no tenant**, so it reads only what is about it, through `app.user_id` (below).

## Two account pools
`users` holds both. `role='resident'` ⇒ tenant-less (CHECK `user_role_matches_tenant_presence`: Super Admin and
resident ⇒ tenant NULL; everyone else ⇒ tenant set). Email and phone are unique **within a pool**:

| Constraint | Pool |
|---|---|
| `unique_active_email_lower`, `unique_active_phone` | staff (`role <> 'resident'`) |
| `unique_active_resident_email_lower`, `unique_active_resident_phone` | resident (`role = 'resident'`) |

So one person can hold a staff login and a resident login on the same address. Every lookup by email/phone names
its pool: `User.objects.staff_pool()` / `.resident_pool()` / `.pool_of(user)`.

- `ActiveEmailBackend` (the **only** entry in `AUTHENTICATION_BACKENDS`) is staff-pool-only, so Django admin and
  `/auth/login/` are unchanged and can never reach a resident account.
- `ResidentEmailBackend` is **not** registered in settings; only the resident login serializer calls it.
- `UserManager.get_by_natural_key` is staff-only.
- The project default permission is now `IsAuthenticatedStaffPool` (signed in **and** not a resident): a view that
  never opted in cannot be reached by a resident. Shared views (`/auth/me/`, password change, account deletion,
  devices, push subscriptions) name `IsAuthenticated` explicitly.

### Release gate for migration `accounts.0013`
The migration **refuses to run** if any `role='resident'` user already exists (nothing created one before, but a
source search cannot prove deployed data is clean). Before releasing, run `manage.py check_resident_users` against
the target database (added to the release checklist, docs/deployment-manual.md §17). Zero rows → proceed. Any rows →
**stop the release**: they need a separately reviewed change, which must include (a) a staged migration (validate,
change the constraint, move approved users to tenant-less accounts, bump `auth_version`) **and** (b) a revision of
this guard, which as written rejects every resident-role user.

## Request context: `app.user_id`
A third session GUC beside `app.tenant_id` and `app.is_super_admin`, handled by the same helpers
(`set_tenant_context`, `_current_context`, `tenant_context`, `clear_tenant_context`).

- `TenantJWTAuthentication` sets it **for resident accounts only**; staff never do. The middleware clears all three.
- `tenant_context(tenant_id)` **keeps** the request's `app.user_id` unless told otherwise (`user_id=None` drops it),
  so a service that enters a PG's tenant to act for the signed-in person still satisfies user-keyed policies.
- `X-Residency-Id` is **optional context**: discovery, join-code lookup, link requests, invite acceptance, account
  settings, deletion and `GET /me/residencies/` work without it. Only endpoints built on `ResidencyScopedAPIView`
  require it (400 `residency_required`). It must name one of the caller's own links (looked up through the user
  clause; anything else → 403 `residency_not_found`, the same answer as "does not exist"). Only then is the link's
  tenant entered.

## Data model (as-built)
All three are tenant tables (`tenant_id`, forced RLS). `resident_id` + `tenant_id` form a composite FK to
`residents (id, tenant_id)` (new `UNIQUE(id, tenant_id)` on `residents`), so a link's tenant is always its record's.

```
resident_access            (ResidentAccess)  — the link; created only by accept-invite or approve-request
  id, tenant_id, user FK→users CASCADE, resident FK→residents PROTECT
  origin (invite | link_request), status (active | revoked | expired)
  granted_by, revoked_by FK→users SET_NULL
  activated_at, revoked_at
  exited_at, access_expires_at        the post-exit clock (see "Access lifecycle")
  UNIQUE(resident) WHERE status='active'                     -- at most one live link per record

resident_invites           (ResidentInvite)  — a pending offer to an EMAIL; never creates a User
  id, tenant_id, resident FK PROTECT, email (copied from the record when sent)
  token_hash (sha256 of the secret; the secret is minted on the worker), expires_at
  status (pending | accepted | expired | cancelled), cancel_reason (staff | resent | access_granted | resident_left)
  invited_by, cancelled_by, accepted_by FK→users SET_NULL, accepted_at
  resulting_access FK→resident_access SET_NULL       -- what accepting created
  UNIQUE(resident) WHERE status='pending'

residency_link_requests    (ResidencyLinkRequest) — a person asking to be linked to a PG (names a PROPERTY, not a record)
  id, tenant_id, requester FK→users CASCADE, property FK PROTECT
  message(≤500), claimed_name, claimed_phone, claimed_room       display only — never trusted or auto-matched
  status (pending | approved | rejected | cancelled), cancel_reason (requester | access_granted)
  resolved_by FK SET_NULL, resolved_at, resolution_note(≤200), resolved_resident FK SET_NULL
  resulting_access FK SET_NULL                       -- so retrying an approval returns the same link
  UNIQUE(requester, property) WHERE status='pending'

properties:       + join_code CHAR(8) NULL (UNIQUE WHERE NOT NULL), join_code_rotated_at
platform_config:  + resident_invite_ttl_hours (168), resident_post_exit_access_days (90),
                    unverified_resident_purge_days (14)
otp_codes:        + purpose 'password_reset'
```

**RLS.** `resident_invites`: the standard tenant policy. `resident_access` and `residency_link_requests`: **one
policy per command** (`apps.core.rls.enable_rls_with_user_select`). SELECT is `tenant match OR user_id = app.user_id
OR super admin`; INSERT/UPDATE/DELETE are tenant-only. This matters: PostgreSQL ORs permissive policies of the same
command, so a single `FOR ALL` policy with the user clause would let the person update or delete their own row. The
tests prove the user clause is SELECT-only.

**Join code.** 8 characters from `ABCDEFGHJKLMNPQRSTUVWXYZ23456789` (no look-alikes), drawn with `secrets`, stored
upper-case, unique. Generated by `Property.save()` on first save; the unique index is the authority on collisions
(RLS hides other tenants' rows from a pre-check). Migration `properties.0012` backfills existing properties. **A
join code identifies a PG and nothing else: it never grants access, it only lets a verified person create a
*pending* request.**

## Access lifecycle
### Staff invite (needs the record's email)
`POST /residents/{id}/app-invite/` → a `ResidentInvite` + an email with `…/join#token=…`. **No `User` is created.**
The secret is minted **on the worker** that sends the mail (so it never travels through the broker); a resend
cancels the old invite, so the old link stops working. The token is `django.core.signing`-signed
`{tenant, invite, secret}`; the signed tenant lets accept enter the right tenant from a tamper-proof source.

`POST /me/invites/accept/ {token}` — **always authenticated**. The person signs up (or in), verifies their email, then
accepts. Needs a **verified email equal to the invite's** (a forwarded link is useless to anyone else). Atomic, under
the resident lock; re-checks token, expiry, eligibility and "no other active link". **A retry by the same user returns
`resulting_access` in its current state** — including revoked or expired; it never creates or reactivates access.
Accepting also cancels **that user's own** pending request for the record's property (others' stay pending).

### Link request (the person asks)
`GET /me/join-codes/{code}/` (verified resident; throttled) → `{name, city}` only; an unknown, malformed,
inactive-property or blocked-tenant code are all the same 404. `POST /me/link-requests/ {join_code, message?,
claimed_name?, claimed_phone?, claimed_room?}` → a pending request (idempotent per person+property).
Staff: `GET /residency-link-requests/` (scoped to visible properties, with display-only `possible_matches`), then
`POST …/{id}/approve/ {resident_id}` or `…/reject/ {note}`. Approval needs an **explicit** `resident_id`: the record
must belong to the request's property, be one the staff member can see, be Reserved/Active/Notice Period, and have no
active link. It also cancels the record's pending invite. Retrying an approval with the same record returns the same
link.

### Revoke, exit, expiry
- `POST /residents/{id}/app-access/revoke/` → `revoked`. Idempotent. Every scoped request re-checks the link, so
  logging in again changes nothing. The person keeps their account and any other PG's link. A re-invite needs a fresh
  acceptance.
- `record_exit(resident)` runs in the same transaction as every transition to Vacated / Absconded / Blacklisted (the
  vacate, abscond and blacklist services and the bare status endpoint). It sets `exited_at` **only if null** and
  `access_expires_at = exited_at + resident_post_exit_access_days`, so Absconded → Blacklisted never restarts or
  extends the window. It also withdraws a pending invite (`resident_left`).
- **Access ends at the timestamp, not when a job runs.** `residency_scope()` compares `access_expires_at` to `now()`
  on every request. The nightly `tidy_resident_access` only flips `status` to `expired` for tidy lists.

### Scope (evaluated per request; `Scope`: none < bills < reserved < full)
Precedence: (1) link status/expiry — revoked or past expiry ⇒ **nothing**, and nothing below can restore it; (2) the
record's status narrows what is left; (3) a suspended/cancelled tenant narrows to Bills. A later step only narrows.

| State | Scope |
|---|---|
| active link, record Active / Notice Period, tenant OK | **full** |
| active link, record Reserved | reserved (profile, notices, bills) |
| active link, record exited, before `access_expires_at` | **bills** (own invoices, payments, receipts, deposit settlement) |
| tenant suspended / cancelled | **bills** at most |
| revoked, past expiry, or record Inquiry; tenant deleted | none → 403 `residency_inactive` |
| record exited but `access_expires_at` never set | none (fail closed) |

## Auth endpoints (`/api/v1/auth/resident/…`; own throttle scopes)
```
POST signup/                 {email,first_name,last_name?,language_code?,website(honeypot)}  → 201, same answer for any address
POST login/                  {email,password}  → tokens; 401 until the address is verified and a password set
POST otp/email/request/      {email}           → emails a 6-digit code (also how an unverified address is verified)
POST otp/email/verify/       {email,code,password?} → tokens; marks the email verified; on FIRST verification sets the password
POST password-reset/         {email}           → emails a reset code
POST password-reset/confirm/ {email,code,new_password}  → sets the password, verifies the email, bumps auth_version
```
Shared with staff, bound to the user id: `token/refresh/`, `password/change/`, `me/`, `account/deletion/*`.
Verification and reset use **codes, not links**: the app has no page to open a link in, and codes work on the web too.
A weak new password is rejected before the reset code is spent. Signup never reveals whether an address exists: an
existing verified account gets a "you already have an account" email instead of a code, and the same hashing time is
spent either way. Staff `/auth/*` endpoints are pinned to the staff pool.

## Other endpoints (`/api/v1/`)
```
STAFF (manage_residents; scoped to visible properties)
GET   /residents/{id}/app-access/            the card: eligible, can_invite, current link, latest invite
POST  /residents/{id}/app-invite/            send (or resend) an invite                 201
POST  /residents/{id}/app-invite/cancel/     cancel the pending invite (idempotent)
POST  /residents/{id}/app-access/revoke/     revoke the active link (idempotent)
GET   /residency-link-requests/ , /{id}/     review requests          POST …/approve/  …/reject/
STAFF (edit_properties)
GET   /properties/{id}/join-code/            POST …/rotate/   (old code stops at once; pending requests stay valid)
PERSON (resident-pool account)
GET   /me/residencies/                       every link with its current scope; no header needed
GET   /me/join-codes/{code}/                 {name, city}          (verified; 20/h)
GET/POST /me/link-requests/                  list mine / create    (verified; POST 10/h)
POST  /me/link-requests/{id}/cancel/
POST  /me/invites/accept/ {token}            (20/h)
```
Property names on the person's own lists are read **per PG, inside that PG's tenant context** — joining `properties`
from a tenant-less row would silently drop it (RLS).

## Account deletion (Module 22 extension)
A resident account may request deletion (`SELF_SERVICE_ROLES` now includes `RESIDENT`); the existing request →
confirm (password or emailed code) → grace → purge flow applies, and the account **locks on request**. Deleting the
account removes the person's login and their own rows; **the PG's records stay** (the Resident, invoices, payments,
invites). A tenant purge removes the PG's side of every link and leaves the person's account alone.

| Reference | On resident-account purge |
|---|---|
| `ResidentAccess.user`, `ResidencyLinkRequest.requester` | CASCADE |
| `ResidentInvite.accepted_by` / `invited_by` / `cancelled_by`, `ResidentAccess.granted_by` / `revoked_by`, `ResidencyLinkRequest.resolved_by` | SET_NULL |
| OTP codes, devices, push subscriptions, notification prefs/logs | purged |
| Audit rows the person acted in (any PG's log) | IP removed; rows naming them redacted |

`DISPOSITION` gained the three tables (`PURGE` for a tenant purge, `RETAIN` for a staff purge). A nightly
`purge_unverified_resident_accounts` removes accounts that never verified within
`unverified_resident_purge_days`, skipping anyone with a link, a link request or an open deletion request.

## Notifications
`residency_link_requested` (Owner + assigned staff with `manage_residents`; email + push) and
`residency_link_resolved` (the requester; email + push), seeded in en + te (`notifications.0011`).
The invite email is a direct templated email to the address (no `User` exists to notify).

## Lock order
Every writer in `access.py` takes **Resident → ResidentInvite / ResidentAccess / ResidencyLinkRequest**, then re-checks
eligibility and "no other active link" inside it (the partial unique index is the backstop). This extends the existing
exit-workflow order **Resident → Vacate → Bed → Subscription** (`services.lock_resident`); the access rows are taken
after the Resident lock and before nothing else, so no cycle with the vacate/abscond/blacklist flows is possible.
Credential paths (signup, reset, login) never take part. *For Module 25:* it must reconcile **Subscription → listing
→ … → Resident** with the existing Resident → … → Subscription order (see that spec).

## Permissions
`manage_residents` (Owner, Manager, Super Admin) for invites, revoke, link requests; `edit_properties` for the join
code. Residents: `IsResidentAccount` / `IsVerifiedResidentAccount` (verified email required to look up a code, ask to
be linked, or accept an invite). A Receptionist cannot invite or approve.

## Decisions
- [DECISION 2026-10-31] **Records and accounts are separate.** A PG's resident record needs no login or email;
  an app account is always created by the person. Staff actions never create a `User`.
- [DECISION 2026-10-31] **One person, many PGs.** Resident accounts are tenant-less and can hold a link per PG, and can
  coexist with a staff account on the same address (per-pool uniqueness).
- [DECISION 2026-10-31] **Linking is explicit on both sides.** Invite (needs the record's email, accepted by a verified
  matching account) or request (join code, approved by staff against a record they choose). Nothing is auto-matched.
- [DECISION 2026-10-31] **After exit:** own bills/receipts only, until a stored expiry; **owner suspended:** bills only.
- [DECISION 2026-10-31] **Codes, not links, for resident verification and reset** (app-first; no page to open a link).
- [DECISION 2026-10-31] **Fail-closed default permission.** `IsAuthenticatedStaffPool` is the project default.
- [DECISION 2026-10-31] **`signup_source` / unusable-password accounts dropped.** Every resident account is self-created
  with a password the person chose, so there is no invite-created account to recover or distinguish.
- [DECISION 2026-11-01] **Password set at email verification, not signup** (review finding): see Auth endpoints. The
  nightly unverified-account cleanup also locks each user and re-checks `email_verified`, links and deletion
  requests inside the delete transaction, so an account verified after the list was taken is never purged. Code verification also decides
  "first verification", spends the code and sets the password in one transaction under the user row lock, so a
  password reset finishing first is never overwritten.
- [DECISION 2026-10-31] **The join-code lookup is a deliberate, narrow cross-tenant read** (`lookup_join_code`): a
  tenant-less person has no tenant, and the code is what names one. One exact-match query as super admin, four fields
  back; inactive properties and blocked tenants look like unknown codes.
- [DECISION 2026-11-01] **Tests that built a resident-role user with a tenant** now build it tenant-less
  (`AuthAPITestCase.create_user`); those tests only assert "a resident is denied".
- [DECISION 2026-11-01] `test_me.test_receptionist_permissions_match_matrix_exactly` was already stale on this branch
  (Module 24 added `view_notices` for the Receptionist); updated while here.

## Open items
- [OPEN] **Module 26b**: `/me/resident/`, `/me/invoices/` (+ invoice PDF — no endpoint exists yet, staff or resident),
  `/me/payments/` (+ receipt), `/me/deposit-settlement/`, `/me/notices/`, `/me/complaints/` (+ photo upload),
  `/me/visitor-requests/` (needs an approval status on `Visitor`, a Module 12 change). Each filters by `resident_id`
  and gets a two-residents-in-one-PG test.
- [OPEN] **Devices/push for resident accounts.** `POST /devices/` and push subscriptions accept any authenticated
  user, but push rows are tenant-scoped (RLS) and a resident has no tenant until a residency is selected. Needs a
  decision in 26b (register under the selected residency's tenant, or a user-keyed table).
- [OPEN] **Notification history/preferences for residents.** `view_own_notifications` already includes `RESIDENT`,
  but the rows are tenant-scoped, so a tenant-less resident sees none.
- [OPEN] **Phone sign-in** for residents without email waits for an SMS vendor (`otp.sms_delivery_available`).
- [OPEN] **Invite deep link.** The email links to `{FRONTEND_BASE_URL}/join#token=…`; the Flutter app link and the web
  page that opens it are not built.
- [OPEN] **Telugu wording** for the two notification types and the resident emails has not had a native review.
- [OPEN] Staff web UI: the "App access" card, the link-request list and the property join code/QR (FE-26).

## Changelog
- 2026-11-01  26a built: pools (`accounts.0013/0014`), `app.user_id`, resident auth, `ResidentAccess` / `ResidentInvite` /
  `ResidencyLinkRequest` (`residents.0010/0011`), join codes (`properties.0012`), config (`core.0010`), notifications
  (`notifications.0011`), deletion extension, nightly tidy, staff/person endpoints.
