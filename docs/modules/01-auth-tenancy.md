# Module: Tenancy, Auth & Roles

> Keep this file in sync with the code AT ALL TIMES.
> If the code and this file disagree, this file is wrong — fix it in the same commit.

**Status:** Done
**Phase:** 1
**PRD reference:** Module 1 (Authentication & Authorization), Section 5 (SaaS Architecture), Section 6 (User Roles & Permissions)
**Depends on:** none
**Blocks:** all

## Purpose
Tenant onboarding with configurable free trial, login (email/password + mobile OTP),
JWT session management, email verification, password reset, the 5-role permission
model, Owner-managed staff accounts, and the tenant-isolation (RLS) infrastructure
every later module builds on.

Client-side how-to for the Flutter app (phone+password login, `auth_version` token
revocation, email-optional staff accounts): [../auth-staff-flutter-integration.md](../auth-staff-flutter-integration.md).

## Data model (as-built)

```
Table: tenants                      (NOT under RLS — root of tenancy)
  id                uuid PK
  name              varchar(200)
  status            trial | active | payment_failed | suspended | cancelled
  default_language  en | hi | te | ta | ml
  trial_ends_at     timestamptz     ← now + PlatformConfig.trial_days at signup
  created_at / updated_at

Table: users                        (NOT under RLS — see Decisions)
  id                uuid PK
  tenant_id         FK → tenants, NULL only for super_admin
                    (DB CHECK: user_role_matches_tenant_presence)
  email             varchar(254) NULL, unique-when-active (case-insensitive: unique_active_email_lower)
  phone             varchar(32) NULL, unique-when-active (unique_active_phone)
  first_name / last_name
  role              super_admin | owner | manager | receptionist | resident
  language_code     en | hi | te | ta | ml (per-user, PRD i18n)
  email_verified    bool            is_active  bool
  password          bcrypt-sha256
  auth_version      int (default 0) ← bumped on password changes for instant revocation
  module_access     jsonb NULL      ← Owner-configured staff access, see "Module access" below
                                     {"base_role": "<role>", "levels": {module: level}}; NULL = role defaults
  created_at / updated_at
  (DB CHECKs: user_requires_email_or_phone, user_owner_superadmin_requires_email,
              user_staff_requires_phone, user_email_not_blank, user_phone_not_blank)

Table: otp_codes                    (NOT under RLS — auth layer)
  id uuid PK · user FK · code_hash · expires_at · attempts · used · created_at

Table: audit_logs                   (RLS ENFORCED — first RLS table)
  id uuid PK · tenant_id uuid NULL (NULL = platform-level action)
  actor FK users (SET_NULL) · action · object_type · object_id
  before jsonb · after jsonb · ip_address · created_at

Table: platform_config              (singleton, id=1)
  trial_days (default 45; PRD says 60, owner changed it 2026-10-18) · payment_grace_days (default 5) · updated_at
  trial_reminder_first_days_before (default 15)   -- added by Module 14
  trial_reminder_second_days_before (default 5)   -- added by Module 14
  support_email · support_phone · support_whatsapp · support_website · support_hours  -- blank = channel not offered
```

### RLS infrastructure (apps/core/)
- `rls.py` — `enable_rls('<table>')` returns the RunSQL for migrations:
  ENABLE + **FORCE** ROW LEVEL SECURITY + `tenant_isolation` policy on
  GUCs `app.tenant_id` / `app.is_super_admin` (USING + WITH CHECK).
- `tenancy.py` — `set_tenant_context()`, `clear_tenant_context()`, and nestable
  `tenant_context()` context manager (Celery/scripts must use it).
- `authentication.py` — `TenantJWTAuthentication`: rejects suspended/cancelled
  tenants (`SUBSCRIPTION_SUSPENDED`), verifies `token.auth_version == user.auth_version`
  (`PASSWORD_CHANGED`), then sets the GUCs for the request.
- `middleware.py` — `TenantContextMiddleware` clears GUCs after every request.
- `exceptions.py` — handler guarantees uppercase machine-readable `code` on errors.
- **The app connects as non-superuser `app_user`** (docker/postgres/init.sql);
  superusers bypass RLS, so this is load-bearing, and a test asserts it.

## API endpoints
```
POST /api/v1/auth/signup/                  tenant + owner + trial          AllowAny (throttled 10/h)
POST /api/v1/auth/verify-email/            signed-token verification       AllowAny
POST /api/v1/auth/resend-verification/     silent resend                   AllowAny
POST /api/v1/auth/login/                   email+pw → JWT pair w/ claims   AllowAny (10/min)
POST /api/v1/auth/login-phone/             phone+pw → JWT pair w/ claims   AllowAny (10/min)
POST /api/v1/auth/token/refresh/           refresh + suspension + auth_ver AllowAny
POST /api/v1/auth/otp/request/             issue OTP (silent)              AllowAny (3/min)
POST /api/v1/auth/otp/verify/              phone+code → JWT pair           AllowAny (10/min)
POST /api/v1/auth/password-reset/          silent reset email              AllowAny (5/min)
POST /api/v1/auth/password-reset/confirm/  set pw + mark email verified    AllowAny
GET|PATCH /api/v1/auth/me/                 profile + tenant + permissions  IsAuthenticated
GET /api/v1/support/                       platform support contacts       AllowAny (public, cached 5 min)
GET|PATCH /api/v1/tenants/current/           detail/update tenant default    manage_tenant_settings
GET|POST /api/v1/staff/                    list/create Manager|Receptionist  manage_staff_accounts
GET|PATCH /api/v1/staff/{id}/              detail/update/deactivate          manage_staff_accounts
POST /api/v1/staff/{id}/set-password/      Owner-set/reset staff password  manage_staff_accounts
GET|PUT|DELETE /api/v1/staff/{id}/module-access/  read / replace / reset a staff     manage_staff_accounts
                                           member's module access (see below)
```
JWT claims: `tenant_id`, `role`, `language`, `auth_version`. Access 15 min / refresh 7 days.

## Business rules (each maps to a test)
1. Signup creates Tenant (status=trial) + Owner; `trial_ends_at` comes from
   PlatformConfig.trial_days — changing config changes the result, no deploy.
2. Login is blocked until email is verified (`EMAIL_NOT_VERIFIED`).
3. Suspended/cancelled tenant: login, refresh, AND existing access tokens all
   rejected with `SUBSCRIPTION_SUSPENDED` (force logout ≤ 15 min).
4. OTP: hashed at rest, single-use, 5-min TTL, max 5 attempts, new request
   invalidates previous codes, unknown phone/email responses are silent.
5. Password-reset confirm also sets `email_verified` (completes staff invites).
6. Staff accounts restricted to manager/receptionist roles; created without a
   password + invite email; deactivation blocks login; no hard delete.
7. Staff queries are tenant-scoped (cross-tenant detail → 404).
8. Role/deactivation changes and staff creation write audit logs (before/after).
9. RLS: tenant context sees only its rows; no context sees none; super admin
   context sees all; cross-tenant INSERT rejected by the database itself.
10. Auth endpoints are rate limited (429 past the configured rate).
11. `/me` exposes the caller's resolved permissions (role matrix adjusted by module access);
    frontend renders from it (F8).
12. Module access resolves fail-closed (table below); owner-only and notification codes are
    never grantable; Owner/Super Admin/Resident ignore any override.
13. A staff member's module access can only be changed by an Owner (`manage_staff_accounts`),
    never by themself; cross-tenant ids are 404.
14. Module-access writes and role changes share one row-locked transaction; every write is
    audited (`staff.module_access_updated` / `staff.updated`) with before/after and IP.

## Permissions
`apps/core/roles.py` holds `Role` + `PERMISSION_MATRIX` (the PRD §6 table, plus `view_dashboard`
and `view_finance`). `require_permission('<perm>')` DRF class factory (+
`require_permission_by_method(read, write)` using DRF `SAFE_METHODS`) + `IsSuperAdmin`.
Every check and `/auth/me/` resolve through `permissions_for_user(user)` — the role matrix
**adjusted by the staff member's module access** — never through the bare role.

### Module access (owner request 2026-10-12)
`apps/core/modules.py` is the server-owned registry. A *module* groups existing permission codes;
a *level* (`off < view < full`) is cumulative (a level's codes = union of every level up to it).

| module | view | full adds |
|---|---|---|
| dashboard | – | `view_dashboard` (UI visibility only) |
| properties | `view_property_features` | `manage_property_features`, `manage_rooms_beds`, `manage_property_settings` |
| tenants | `view_resident_profile` | `manage_residents`, `manage_admissions`, `manage_allocations`, `manage_deposits` |
| finance | `view_finance`, `view_activity_timeline` | `manage_invoices`, `manage_payments`, `manage_discounts` |
| reports | – | `view_reports` |
| complaints | – | `manage_complaints` |
| visitors | – | `manage_visitors` |

Dashboard/Reports/Complaints/Visitors support only Off/Full (their `manage_*` code covers reads and
writes). Never grantable (role-only): `manage_properties`, `manage_staff_accounts`,
`assign_staff_to_properties`, `manage_tenant_settings`, `manage_subscription`, `view_audit_logs`,
`manage_tenants`, notification codes. `ROLE_DEFAULT_LEVELS` is hand-written (manager: everything
Full; receptionist: properties/tenants View, visitors Full, rest Off) and a test pins it to
`PERMISSION_MATRIX`.

Resolution of stored `module_access` for a staff role (everything else → plain role permissions):

| stored value | result |
|---|---|
| NULL | role defaults |
| non-dict / dict without `base_role` (incl. raw `{}`) | every module off |
| `base_role` ≠ current role | role defaults (a role change voids the override, by any path) |
| `levels` missing or not a dict | every module off |
| module missing from `levels` (registry grew) | that module off |
| unknown module key | ignored |
| invalid/unsupported level | that module off |

API: `GET` returns `{role, customized, modules:[{key, levels, level, default_level}]}`; `PUT
{role, levels}` is a **complete replacement** (all modules required; unknown/unsupported → 400;
`role` mismatch → `409 {"code": "ROLE_CHANGED"}`); `DELETE` resets to role defaults. Levels equal
to the role defaults are stored as NULL. Changing a staff member's role clears the override.

## Edge cases handled
- Same email or phone across tenants → superseded by `[DECISION 2026-10-10]`: unique only among active accounts; deactivation frees the identifier for re-employment under a new tenant.
- Suspension between token issuance and use → caught at authentication.
- Password change between token issuance and use → `auth_version` mismatch triggers immediate rejection with `PASSWORD_CHANGED`.
- OTP for unverified email → phone possession proven; does not gate on unverified email.
- Phone login for staff with unverified/absent email → succeeds without requiring email verification.
- Nested `tenant_context()` restores the previous context (audit writes inside
  a request don't clobber the request's context).
- Requests that never touch the DB don't open a connection just to clear GUCs.

## Open questions / Decisions
- [DECISION 2026-07-02] `users`, `tenants`, `otp_codes` are NOT under RLS:
  authentication must look up users before any tenant context exists. User
  queries are app-level scoped instead; every business table from Module 02 on
  MUST use `enable_rls()` + an isolation test.
- [DECISION 2026-07-02] App connects as non-superuser `app_user` (created by
  docker/postgres/init.sql; on pre-existing volumes create it manually). RLS
  test fails loudly if the connection can bypass RLS.
- [DECISION 2026-07-02] PlatformConfig (core) singleton holds trial_days /
  payment_grace_days now (invariant 10); per-plan caps land on the Plan model
  in Module 13, which also owns tenant status transitions.
- [DECISION 2026-07-02] Staff–property assignment deferred to Module 02 (needs
  the Property model). Staff CRUD without assignment lives here.
- [DECISION 2026-07-02] Email globally unique (not per-tenant); phone unique
  when set because OTP login resolves the user by phone alone. **(Superseded 2026-10-10: uniqueness is scoped to `is_active=True`, freeing identifiers upon deactivation for cross-tenant re-employment).**
- [DECISION 2026-07-02] OTP delivery is a stub (`accounts/otp.py:_deliver`,
  logs the code; console email backend in dev). SMS provider is V2 (PRD 18).
- [DECISION 2026-09-10] **`otp.verify` runs in a transaction and
  `select_for_update()` the OTP row.** The failed-attempt counter was a
  read-modify-write with no lock: N concurrent verify requests all read
  `attempts=0` and all get a guess, so the `OTP_MAX_ATTEMPTS` lockout on a
  6-digit code was defeated by parallelism. The lock serializes verifies for
  one user.
- [DECISION 2026-09-10] **DRF throttle state uses a shared Redis cache in
  prod.** With no `CACHES` configured it fell back to per-process
  `LocMemCache`, so `login` / `otp_verify` / `password_reset` / `signup`
  limits (a PRD Module 1 security requirement) were multiplied by worker count
  and reset every deploy. `base.py` now points `default` at Redis (DB 1);
  `dev.py` keeps `LocMemCache` (single-process, and `manage.py test` has no
  Redis).
- [DECISION 2026-07-02] Staff invites reuse the password-reset token; the
  confirm endpoint marks email verified since possession is proven.
- [DECISION 2026-07-02] AuditLog model created now (invariant 9 applies from
  Module 01); Module 15 adds the read API. It is the first RLS-enforced table.
- [DECISION 2026-07-02] Cancelled tenants are blocked identically to suspended
  (same error code); data-retention handling is Module 13's concern.
- [DECISION 2026-07-02] In tests, authenticate with real JWTs (see
  `tests/base.py:authenticate`) — `force_authenticate` skips the RLS context.
- [DECISION 2026-07-03] `manage_property_settings` widened from Owner-only to
  Owner+Manager. The PRD §6 matrix table said Owner-only, but Module 2B's
  prose and its own settings summary table both say "Configurable By: Owner,
  Manager" — confirmed with the product owner that Module 2B is correct.
  `PERMISSION_MATRIX` in `apps/core/roles.py` updated accordingly (Module 03).
- [DECISION 2026-10-10] **Phone+password login as MVP staff path**: Since SMS
  provider is not yet integrated, staff log in using phone + password via
  `POST /api/v1/auth/login-phone/`. Phone is mandatory for Manager/Receptionist;
  email remains optional for staff (unconditionally required for Owner/Super Admin).
- [DECISION 2026-10-10] **Active-only uniqueness & Re-employment**: Superseding
  the 2026-07-02 decision, email and phone uniqueness is scoped to active accounts
  (`UniqueConstraint(Lower('email'), condition=Q(is_active=True))` and
  `UniqueConstraint(fields=['phone'], condition=Q(is_active=True))`). Deactivating an
  account frees its phone and email so the person can be re-employed under a different
  tenant with a brand new, independent account.
- [DECISION 2026-10-10] **Strict phone canonicalization**: Numbers normalize to
  canonical 10 digits starting with 6-9 from shapes: 10 digits, 11 digits starting with 0,
  or 12 digits starting with 91. All other shapes (e.g. 13-digit numbers or invalid prefixes)
  are rejected outright without truncation.
- [DECISION 2026-10-10] **Token revocation via integer `auth_version`**: Rather than a
  wall-clock timestamp comparison against JWT `iat` (which suffers from same-second
  precision holes), an integer `auth_version` counter is stored on `User` and stamped in
  tokens. `set_password()` and `set_unusable_password()` automatically flag `auth_version`
  for increment in `save()`, atomically revoking all active access and refresh tokens on password
  change. Rollout decision: Pre-deploy JWTs lack this claim and are deliberately force-logged-out.
- [DECISION 2026-10-10] **DB constraint `user_staff_requires_phone`**: In addition to serializer
  checks, a DB CheckConstraint enforces that Manager and Receptionist roles must have a non-null
  phone number.
- [DECISION 2026-10-10] **Login verification gate separation**: The email-verification gate is
  confined to the email+password login path (`POST /auth/login/`). Phone+password login and
  mobile OTP verify do not gate on unverified email.
- [DECISION 2026-10-10] **Narrow save on password reset**: Password changes via
  `StaffViewSet.set_password` use `instance.save(update_fields=['password', 'updated_at'])` to
  prevent concurrent deactivations or profile modifications from being overwritten by stale model
  instances. `User.save()` preserves narrow updates and normalizes only fields present in `update_fields`.
- [DECISION 2026-10-10] **Profile phone clearing constraints**: `MeUpdateSerializer` explicitly
  blocks Manager and Receptionist roles from removing their phone number via `PATCH /auth/me/`,
  preventing database constraint violations (`user_staff_requires_phone`). `api_exception_handler`
  also maps this constraint to a 400 Bad Request (`PHONE_REQUIRED`) error as defense-in-depth.
- [DECISION 2026-10-10] **Cryptographically secure staff credential generation**: Staff passwords
  generated in the UI use `crypto.getRandomValues()` with rejection sampling (eliminating modulo
  bias) and deterministic satisfaction of all configured Django password validators
  (`MinimumLengthValidator`, `NumericPasswordValidator`, `CommonPasswordValidator`,
  `UserAttributeSimilarityValidator`).

- [DECISION 2026-10-12] **Per-staff module access supersedes the fixed-matrix stance of PRD §6.**
  The PRD defines one fixed permission set per role and no owner-configurable permissions; the
  product owner asked for a Team Management screen where the Owner tunes each Manager's /
  Receptionist's access per module. Confirmed scope: *generic levels first* (Off/View/Full where a
  module supports them, built from existing permission codes — named narrow presets such as
  "Move Out" need new narrow codes and are deferred) and *role sets the defaults, modules override
  per person* (Role stays; overrides are stamped with `base_role` so a role change by any path
  voids them). The registry, role defaults and resolution rules are above.
- [DECISION 2026-10-12] **Finance vs Tenants boundary.** Finance governs invoices, payments,
  discounts, their exports and the billing money fields (`contracted_rent`, `billing_mode`) on
  resident/bed views (`view_finance`). Tenants→Full deliberately includes the move-out workflow
  (vacate, deposit refund, write-off, absconded, blacklist — all `manage_deposits`), so the
  deposit-settlement figures (`security_deposit_amount`, `advance_amount`, `advance_refundable`)
  are visible with `view_finance` **or** `manage_deposits`. Tenants→Full + Finance→Off can process
  a move-out but cannot read invoices/payments/discounts, rent or billing mode. Rejected: moving
  deposits into Finance or requiring both (either stops Tenants→Full staff from processing
  move-outs). The resident timeline needs `view_resident_profile` **and** `view_activity_timeline`;
  `BedSerializer.current_occupant` is null without `view_resident_profile`, `history` needs both.
- [DECISION 2026-10-12] **"Off" honesty limits (documented, not bugs).** Property / building /
  floor / room / bed GETs stay role-based (`CanViewProperties`) for assigned staff: they are the
  structural backbone (property switcher, admission bed picker), so Properties=Off hides the
  Properties screens and management but not those reads. `view_dashboard` is a UI-visibility code
  only — each dashboard card's data is still enforced by its own module. Properties→Full includes
  property settings (late fees, penalties) — an Owner revokes that by choosing Properties→View.
  Revoking Complaints does not unassign complaints already assigned to that person.
  `CanConfirmVisitor` stays Owner/Manager-only *and* now requires `manage_visitors`.
- [DECISION 2026-10-12] **Writes are race-safe.** `PUT module-access` carries the role the client
  rendered and answers `409 ROLE_CHANGED` if it changed; both it and `PATCH /staff/{id}/` run
  inside the `locked_staff` context manager (`apps/accounts/staff_access.py`: `atomic` +
  `select_for_update`, kept open through validation, save and audit), so a role change and a
  module-access change can never interleave on stale data.
- [DECISION 2026-10-12] **Reductions are enforced by the API immediately** (`request.user` is
  loaded per request; no `auth_version` bump). The staff member's *visible* UI stays stale until
  `/auth/me/` is refreshed: the frontend refreshes on tab focus (throttled to 60 s) and, without
  throttle, after any 403.
- [DECISION 2026-10-12] **Registry growth warning.** When a module is added to
  `apps/core/modules.py`, staff with a saved override resolve the new module to `off`
  (fail-closed — they do *not* inherit the role default); only never-customized staff (NULL) pick
  up the new role default. A release that adds a module must decide whether to backfill existing
  overrides with a data migration. Likewise `edit_properties` (on the unmerged
  `feature/property-map-location` branch) must be added to Properties→Full when that merges — the
  registry↔matrix consistency test fails until someone does.
- [DECISION 2026-10-12] Frontend autosave coalesces: toggles apply optimistically and one worker
  sends the latest complete map after the in-flight request (controls stay enabled while saving,
  a failed save rolls back to the last server-confirmed state, `409 ROLE_CHANGED` reloads).

## Changelog
- 2026-06-xx  Created stub.
- 2026-07-02  Built: tenancy/RLS infra, Tenant/User/OtpCode/PlatformConfig/
  AuditLog models, full auth API, staff management, permission matrix,
  49 tests (RLS proof included). Spec rewritten to as-built.
- 2026-07-03  `manage_property_settings` widened to include Manager (see
  Decisions) while building Module 03.
- 2026-07-04  Module 13 added one line to `SignupSerializer.create`: every
  new tenant also gets a blank `Subscription` row (no plan yet). No other
  change to the signup flow itself.
- 2026-07-04  Module 14 changed `SignupSerializer.create`'s email dispatch:
  `send_verification_email` now runs via a Celery task
  (`apps.accounts.tasks.send_welcome_email_task`, doubling as the "welcome"
  notification) deferred with `transaction.on_commit`, instead of a direct
  synchronous call. Added two `PlatformConfig` fields (trial-reminder
  offsets). See Module 14's spec for the full notification design.
- 2026-07-04  Module 15 added the `view_audit_logs` permission (Owner +
  Super Admin) to `PERMISSION_MATRIX` and built the read-only query API over
  `AuditLog` (this module's model + write path are unchanged). See Module
  15's spec.
- 2026-10-06  Module 18 added `view_property_features` (Owner, Manager, Receptionist) and
  `manage_property_features` (Owner, Manager) to `PERMISSION_MATRIX`.
- 2026-10-10  Staff phone+password login (`POST /api/v1/auth/login-phone/`),
  cross-owner re-employment (uniqueness scoped to `is_active=True`), identifier
  normalization, `auth_version` instant token revocation on password change,
  Owner-driven staff initial password and password reset (`POST /api/v1/staff/{id}/set-password/`)
  with atomic audit logging, `user_staff_requires_phone` DB constraint, and frontend Staff
  Management page (`(owner)/staff/`) with full i18n.
- 2026-10-12  Owner-configurable per-staff module access (see Permissions → Module access and the
  `[DECISION 2026-10-12]` entries): `User.module_access` (migration 0005), `apps/core/modules.py`
  registry, `permissions_for_user`, `require_permission_by_method`, `view_dashboard` /
  `view_finance` codes, `GET|PUT|DELETE /staff/{id}/module-access/`, row-locked
  `PATCH /staff/{id}/`, billing viewsets split read (`view_finance`) from write (`manage_*`),
  finance exports on `view_finance`, resident/bed money-field visibility on Finance, and the Team
  Management screen (`(owner)/staff/[id]`) replacing the old Manage Property Access modal.
- 2026-10-16  UX roadmap backend:
  - `tenants.fiscal_year_start_month` (1–12, default 4 = Indian FY; migration
    `accounts.0006`), readable/editable on `GET|PATCH /tenants/current/`
    (`manage_tenant_settings`); any changed field of that endpoint is now
    audit-logged with before/after, not only `default_language`.
  - New permission codes `view_expenses` / `manage_expenses` (`_OPS`) and
    module-access entry `expenses` (off / view / full; Manager full,
    Receptionist off). Data migration `accounts.0007` sets `expenses: full`
    on Managers whose module access was already customized (owner decision —
    otherwise the fail-closed registry would resolve it to off).
  - `PlatformConfig.payment_due_soon_days` (default 7, `core.0004`).
  - Shared helpers: `core.permissions.require_any_permission`,
    `core.redaction.Redactor` (null + `redacted[]` partial responses),
    `core.exceptions.Conflict` (409 with a specific code),
    `core.idempotency` (`Idempotency-Key` header), `core.periods` (months in
    the product timezone; `local_today()` replaces the container-clock
    `date.today()` in new code).
- 2026-10-18  Platform support contacts: `PlatformConfig.support_email|support_phone|support_whatsapp|
  support_website|support_hours` (all blank by default, `core.0006`), edited by a Super Admin in Django
  admin. `GET /api/v1/support/` (public, no auth, `Cache-Control: public, max-age=300`) returns
  `{email, phone, whatsapp, whatsapp_url, website, hours}`; unset channels are `null`; `whatsapp_url` is
  `https://wa.me/<whatsapp>`. Phone/WhatsApp are digits with country code and no `+` (8–15 digits, admin
  validated) so toll-free numbers work. The endpoint is exempt from the app-client 426/503 gate
  (`devices.middleware.EXEMPT_PREFIXES`) so an outdated build or a maintenance window can still show it.
  Read with `filter(pk=1).first()`, never `PlatformConfig.get()`, so a public GET never writes.
  Tests: `apps/core/test_support.py`. These are platform-wide contacts, not per-property/PG contacts.
