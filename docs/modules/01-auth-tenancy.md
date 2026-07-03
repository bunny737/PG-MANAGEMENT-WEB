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
  email             unique          phone  unique-when-set (OTP login key)
  first_name / last_name
  role              super_admin | owner | manager | receptionist | resident
  language_code     en | hi | te | ta | ml (per-user, PRD i18n)
  email_verified    bool            is_active  bool
  password          bcrypt-sha256
  created_at / updated_at

Table: otp_codes                    (NOT under RLS — auth layer)
  id uuid PK · user FK · code_hash · expires_at · attempts · used · created_at

Table: audit_logs                   (RLS ENFORCED — first RLS table)
  id uuid PK · tenant_id uuid NULL (NULL = platform-level action)
  actor FK users (SET_NULL) · action · object_type · object_id
  before jsonb · after jsonb · ip_address · created_at

Table: platform_config              (singleton, id=1)
  trial_days (default 60) · payment_grace_days (default 5) · updated_at
```

### RLS infrastructure (apps/core/)
- `rls.py` — `enable_rls('<table>')` returns the RunSQL for migrations:
  ENABLE + **FORCE** ROW LEVEL SECURITY + `tenant_isolation` policy on
  GUCs `app.tenant_id` / `app.is_super_admin` (USING + WITH CHECK).
- `tenancy.py` — `set_tenant_context()`, `clear_tenant_context()`, and nestable
  `tenant_context()` context manager (Celery/scripts must use it).
- `authentication.py` — `TenantJWTAuthentication`: rejects suspended/cancelled
  tenants (`SUBSCRIPTION_SUSPENDED`), then sets the GUCs for the request.
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
POST /api/v1/auth/token/refresh/           refresh + suspension re-check   AllowAny
POST /api/v1/auth/otp/request/             issue OTP (silent)              AllowAny (3/min)
POST /api/v1/auth/otp/verify/              phone+code → JWT pair           AllowAny (10/min)
POST /api/v1/auth/password-reset/          silent reset email              AllowAny (5/min)
POST /api/v1/auth/password-reset/confirm/  set pw + mark email verified    AllowAny
GET|PATCH /api/v1/auth/me/                 profile + tenant + permissions  IsAuthenticated
GET|POST /api/v1/staff/                    list/create Manager|Receptionist  manage_staff_accounts
GET|PATCH /api/v1/staff/{id}/              detail/update/deactivate          manage_staff_accounts
```
JWT claims: `tenant_id`, `role`, `language`. Access 15 min / refresh 7 days.

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
11. `/me` exposes the PRD §6 permission matrix; frontend renders from it (F8).

## Permissions
`apps/core/roles.py` holds `Role` + `PERMISSION_MATRIX` (exact PRD §6 table).
`require_permission('<perm>')` DRF class factory + `IsSuperAdmin`. Matrix is
serialized on `/auth/me/` as `permissions: [...]`.

## Edge cases handled
- Same email or phone across tenants → rejected globally (see Decisions).
- Suspension between token issuance and use → caught at authentication.
- OTP for unverified email → still gated by `EMAIL_NOT_VERIFIED`.
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
  when set because OTP login resolves the user by phone alone.
- [DECISION 2026-07-02] OTP delivery is a stub (`accounts/otp.py:_deliver`,
  logs the code; console email backend in dev). SMS provider is V2 (PRD 18).
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

## Changelog
- 2026-06-xx  Created stub.
- 2026-07-02  Built: tenancy/RLS infra, Tenant/User/OtpCode/PlatformConfig/
  AuditLog models, full auth API, staff management, permission matrix,
  49 tests (RLS proof included). Spec rewritten to as-built.
- 2026-07-03  `manage_property_settings` widened to include Manager (see
  Decisions) while building Module 03.
