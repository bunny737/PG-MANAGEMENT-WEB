# Module: Tenancy, Auth & Roles

> Keep this file in sync with the code AT ALL TIMES.
> If the code and this file disagree, this file is wrong — fix it in the same commit.

**Status:** Done
**Phase:** 1
**PRD reference:** Module 1 (Authentication & Authorization), Section 5 (SaaS Architecture), Section 6 (User Roles & Permissions)
**Depends on:** none
**Blocks:** all

## Purpose
Tenant onboarding with configurable free trial, login (email/password + mobile OTP,
plus an optional emailed sign-in code),
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
  id uuid PK · user FK · channel (phone | email) · code_hash · expires_at · attempts · used · created_at
  index otp_user_chan_used_idx (user, channel, used, -created_at)  -- verify()'s filter + newest-first

Table: audit_logs                   (RLS ENFORCED — first RLS table)
  id uuid PK · tenant_id uuid NULL (NULL = platform-level action)
  actor FK users (SET_NULL) · action · object_type · object_id
  before jsonb · after jsonb · ip_address · created_at

Table: platform_config              (singleton, id=1)
  trial_days (default 45; PRD says 60, owner changed it 2026-10-18) · payment_grace_days (default 5) · updated_at
  trial_reminder_first_days_before (default 15)   -- added by Module 14
  trial_reminder_second_days_before (default 5)   -- added by Module 14
  support_email · support_phone · support_whatsapp · support_website · support_hours  -- blank = channel not offered

Table: contact_messages             (platform-level, NOT tenant-scoped — no tenant_id, no RLS)
  id uuid pk · name · email · phone (blank) · message (<=2000) · language (Accept-Language at submit)
  ip_address (null) · status (new|handled) · handled_at (null) · created_at
  index (status, -created_at)  -- website contact form inbox, read in Django admin
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
POST /api/v1/auth/verify-email/            signed-token verification       AllowAny (10/min)
POST /api/v1/auth/resend-verification/     queue new link (silent)         AllowAny (5/min per IP + 5/h per email)
POST /api/v1/auth/login/                   email+pw → JWT pair w/ claims   AllowAny (10/min)
POST /api/v1/auth/login-phone/             phone+pw → JWT pair w/ claims   AllowAny (10/min)
POST /api/v1/auth/token/refresh/           refresh + suspension + auth_ver AllowAny
POST /api/v1/auth/otp/request/             issue OTP (silent)              AllowAny (3/min)
POST /api/v1/auth/otp/verify/              phone+code → JWT pair           AllowAny (10/min)
POST /api/v1/auth/otp/email/request/       queue email code (silent)       AllowAny (3/min per IP + 5/h per email)
POST /api/v1/auth/otp/email/verify/        email+code → JWT pair           AllowAny (10/min)
POST /api/v1/auth/password-reset/          silent reset email              AllowAny (5/min)
POST /api/v1/auth/password-reset/confirm/  set pw + mark email verified    AllowAny
GET|PATCH /api/v1/auth/me/                 profile + tenant + permissions  IsAuthenticated
GET /api/v1/support/                       platform support contacts       AllowAny (public, cached 5 min)
POST /api/v1/public/contact/               website contact form -> ContactMessage   AllowAny (public, write-only, throttled 5/h per IP + 3/h per email, 16 KiB body cap)
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
   invalidates previous codes **of the same channel**, unknown phone/email responses are silent.
   A code verifies only on the channel it was issued for.
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
15. Email code login (optional; password stays the default): the request endpoint answers every
    address identically and only queues `send_login_code_task`; the worker issues and emails a code
    only to an active tenant user (Owner or staff with an email; never a Super Admin) whose tenant is
    not suspended/cancelled. A correct code returns the JWT pair (current `auth_version`) and marks the
    email verified in the same transaction that consumes the code. Malformed codes (not 6 digits) are
    a 400 and use no attempt. Tests: `apps/accounts/tests/test_email_otp.py`.
16. Email verification: the link's token is signed `{uid, email}` (72 h) and travels in the URL
    fragment (`/verify-email#token=…`). Verifying locks the user row and requires the account to be
    active and still hold that exact (normalized) address; the link never signs anyone in.
    Verification emails are always sent from a Celery task that re-checks eligibility on the worker:
    signup → `send_welcome_email_task(user_id, expected_email)`; staff creation and Django-admin
    paths → `send_verification_email_to_user_task(user_id, expected_email)`; anonymous resend →
    `send_verification_email_to_address_task(email)`, queued for every address alike. A failed send is
    never recorded as a sent notification. Admin "Send verification email" / "Mark email verified"
    actions and admin email changes are audited; an admin email change resets verification and bumps
    `auth_version`. Tests: `apps/accounts/tests/test_email_verification.py`.

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
- Email code for an unverified email → succeeds and marks the email verified (inbox possession proven).
- Email code issued to an account that is then deactivated, and the address reused by a new account →
  the old code cannot authenticate the new account (verify resolves the active user, who has no code).
- SMTP failure while sending an email code → production retries (each retry issues a fresh code, so only
  the newest delivered code works); the request already got its generic 200 either way.
- Nested `tenant_context()` restores the previous context (audit writes inside
  a request don't clobber the request's context).
- Requests that never touch the DB don't open a connection just to clear GUCs.

## Open questions / Decisions
- [DECISION 2026-10-21] **Email code login is optional; password stays the default** (owner decision).
  Email delivery adds latency and a dependency on the mail provider, and staff may have no email at
  all (phone is their mandatory identifier), so code-only login would lock some of them out. The
  login screen offers "Email me a code instead" in both the Owner and Staff views; each view still
  rejects the other's roles after login.
- [DECISION 2026-10-21] **`otp_codes.channel` (phone | email).** A purpose such as "login" would let a
  new email code cancel an outstanding phone code. Issue invalidates and verify matches only the same
  channel. Migration `accounts.0008` backfills existing rows as `phone`; the default is not kept.
- [DECISION 2026-10-21] **Issuance locks the user row** (`otp.issue`: `select_for_update(of=('self',))`)
  so concurrent requests can't each invalidate the old codes and then both create one. The caller's
  eligibility predicate re-runs on the locked row, so a deactivation, tenant suspension or email change
  between the worker's lookup and the lock is seen; a user deleted before the lock gets `None`.
  **`otp.verify` takes the same user-row lock first, then the code row** (user → OTP, as in issue).
  Locking the code row first and updating `email_verified` afterwards deadlocked against a concurrent
  resend (resend held the user and waited on the code rows; verify the reverse). Pinned by
  `test_verify_locks_the_user_row_before_the_code_row` and a resend-vs-verify race test.
- [DECISION 2026-10-21] **The 30 s resend cooldown is per address and survives navigation.** The last
  request (`{email, sentAt}`) is held by `LoginForm`, which stays mounted while the user switches
  between password and code or between views. Submitting the same address during the cooldown (e.g.
  via "Change email") returns to code entry without a new request. A page reload resets it; the
  backend's per-email throttle (5/h) is the real limit.
- [DECISION 2026-10-21] **The request endpoint does no lookup and no SMTP; the worker generates the
  code.** `EmailOtpRequestSerializer.save()` always calls `enqueue(send_login_code_task, email)`, so
  timing, broker outages (`enqueue` swallows them) and SMTP failures look the same for every address.
  The plaintext code is created on the worker (`tasks.deliver_login_code`) and never enters the Redis
  payload — only the normalized email does. `send_login_code_task.expires = OTP_TTL_SECONDS` drops a
  backlog older than a code's lifetime.
- [DECISION 2026-10-21] **Eager-mode delivery failures are logged, not raised.** Dev/test run Celery
  eagerly with `CELERY_TASK_EAGER_PROPAGATES`, which would turn an SMTP error for a registered address
  into a 500 inside the request while unknown addresses get 200. The task checks
  `self.request.is_eager`: eager → log and return; async (production) → `self.retry` up to 2 times,
  5 s apart, then log. Logs never contain the code or the address.
- [DECISION 2026-10-21] **Super Admins cannot use email code login.** They sign in through Django admin
  behind IAP; the request side never issues them a code and verify only resolves users with a tenant.
- [DECISION 2026-10-21] **A correct email code marks the email verified**, the same trust as completing
  the invite/reset link (possession of the inbox). It happens in `otp.verify`'s transaction, together
  with consuming the code (and sets `updated_at`, which `update()` skips). Callers must not wrap verify
  in an outer transaction they roll back, or failed attempts would stop counting.
- [DECISION 2026-10-21] **Per-email request throttle lives in `apps.accounts.throttles`**
  (`OtpEmailThrottle`, SHA-256 of the normalized email), not a generalized core throttle, so
  `apps.core` does not depend on `accounts` normalization. It ignores unparsable or non-object bodies
  (validation answers 400) instead of raising.
- [DECISION 2026-10-21] **Accepted narrow race:** a tenant suspended just after the locked eligibility
  check can still receive one email, but verify re-checks tenant status, so no tokens are issued.
- [OPEN 2026-10-21] **Forgot-password page is not built.** The login screen's forgot-password form is
  a simulated timeout, and the frontend has no `/reset-password` route although the reset and staff
  invite emails link to it. (`/signup` and `/verify-email` were built 2026-10-21.)
- [DECISION 2026-10-21] **Verification token is bound to the address.** The signed payload is
  `{uid, email}`, and `EmailVerificationSerializer.save()` compares the account's current normalized
  email under `select_for_update()` before marking it verified — so an admin email change can't land
  between the check and the update and get the new address verified by a link sent to the old one.
  Tokens issued before this (uid only) are rejected; the user requests a new link.
- [DECISION 2026-10-21] **The token travels in the URL fragment** (`/verify-email#token=…`), which
  browsers never send to a server, so the 72-hour token stays out of nginx / Next.js / proxy access
  logs. The page reads it client-side and removes it with `history.replaceState`. A `?token=` query
  is accepted as a fallback for hand-edited links; that one has already reached an access log, so the
  fallback only minimizes exposure.
- [DECISION 2026-10-21] **The link never signs the user in.** It stays valid for 72 h and can be
  forwarded or prefetched, so it confirms the address only; the user then signs in with a password
  (or an email code).
- [DECISION 2026-10-21] **Three delivery tasks, account- or address-bound.** Lifecycle emails (signup,
  staff creation, Django admin) are bound to `user_id + expected_email` and skipped if, by the time the
  worker runs, the account is inactive, already verified, or no longer holds that address — so a job
  queued for one account can't mail a link for another account that reused the address. Only the
  anonymous resend is address-based (whoever owns the address now). A welcome job queued before this
  deploy (no `expected_email`) can't prove which address it was for, so it is dropped rather than
  sent; `expected_email` defaults to None only so such a job skips instead of raising. The owner can
  request a link from the sign-in screen. `on_commit` callbacks capture plain values, never model
  objects.
- [DECISION 2026-10-21] **Delivery result contract.** `tasks._deliver` returns `SENT | SKIPPED |
  FAILED` (a `str` Enum, internal — tasks return None). SMTP/OS errors are retried twice, 5 s apart, on
  a worker; in eager mode (dev/test) or after the last retry they are logged without the address and
  return FAILED. The welcome task records the `welcome` notification only on SENT. The email-code
  task uses the same helper.
- [DECISION 2026-10-21] **Resend is always queued.** `ResendVerificationSerializer` normalizes the
  email and calls `enqueue(send_verification_email_to_address_task, email)` for every address: no
  lookup or SMTP in the request, so timing, broker and SMTP failures can't reveal registration.
  Throttled per IP (`resend_verification` 5/min) and per hashed email (`resend_verification_email`
  5/h, `VerificationEmailThrottle`). Staff-creation verification moved to an `on_commit` enqueue, so
  an SMTP failure can no longer roll back the account.
- [DECISION 2026-10-21] **Django admin paths are audited.** `email_verified` is read-only in the change
  form. "Send verification email" writes `user.verification_email_requested_by_admin` ("requested",
  not "sent": `after={'email'}`) **before** enqueueing, so nothing is ever queued without its audit
  record (a failed insert queues nothing). Audit rows are append-only, so a broker failure appends a
  second row, `user.verification_email_queue_failed`. A strict audit/queue atomicity guarantee would
  need a transactional outbox, which isn't warranted for a manual admin action. "Mark email verified"
  locks the rows in pk order and audits `user.email_verified_by_admin` per user. Audit rows exist only
  for eligible users; the skip counts (inactive / no email / already verified) appear in the admin
  message, not the audit log. Creating a user queues the verification email
  (`language_code` is on the add form). Changing a user's email (case-only edits don't count) resets
  `email_verified`, sets `auth_version` from the locked row + 1 (ending every session — the sign-in and
  recovery address changed), audits `user.email_changed_by_admin` and queues a link to the new address.
- [DECISION 2026-10-21] **`SIGNUP_ENABLED` is discovery-only** (owner decision). It controls the
  marketing CTA and the login page's "Start free trial" link; `/signup` and `POST /auth/signup/` stay
  usable by anyone with the URL (useful for onboarding early-access owners by link). There is no
  server-side switch.
- [DECISION 2026-10-19] **Contact form inbox is platform-level, not tenant data.** `ContactMessage`
  (`core.0007`) has no `tenant_id` and no RLS: the sender is an anonymous prospect, so invariant 1 has
  nothing to scope to (same class as `PlatformConfig`, `AppVersionPolicy`). It is readable only through
  Django admin by staff; the public API is write-only (no GET) and never echoes stored data.
- [DECISION 2026-10-19] **Abuse controls for the public form:** body-size cap (413) before parsing, per-IP
  throttle (`contact_message` 5/h) plus per-email throttle (`contact_message_email` 3/h, keyed on a hash of
  the lower-cased email so rotating IPs does not lift it), field validation, and a honeypot field `website`
  — a bot that fills it gets the same 201 but nothing is stored. The request serializer is an explicit
  allow-list (name, email, phone, message, website), so nothing posted can set `status`/`ip_address`.
- [DECISION 2026-10-19] **Admin is read-only with audited status changes.** Content fields are read-only and
  rows cannot be added or edited; staff use the "Mark as handled / new" actions, and deletes (single or bulk)
  are also recorded with `audit_log.record(tenant_id=None)` (invariant 9). Each action runs in one
  `transaction.atomic()` together with its audit writes (a status batch or bulk delete is all-or-nothing, and a
  failing audit write leaves the data unchanged; tests mock the audit call to fail). Audit payloads carry only the id
  and status — never the sender's name, email or text. No email notification is sent (owner decision).
- [OPEN 2026-10-19] **Retention:** `contact_messages` holds personal data (name, email, phone, free text, IP)
  and has no purge job (the devices module has one for installs). Decide a retention period and add a seeded
  periodic task; the privacy policy deliberately promises no number yet.
- [DECISION 2026-10-20] **Trusted client IP (supersedes the 2026-10-19 [OPEN]).** `X-Forwarded-For` is
  never trusted. `apps/core/net.py`: the load balancer overwrites `X-PGLive-Client-IP` on every backend
  (`CLIENT_IP_HEADER`); the Next BFF forwards the browser's address as `X-PGLive-Origin-IP` with an HMAC
  (`BFF_ORIGIN_SECRET`) over `v1\n{ip}\n{ts}\n{METHOD}\n{raw path}\n{raw query}`, verified against gunicorn's
  `RAW_URI` (never decoded `PATH_INFO`), 60 s skew, constant-time compare. `ClientIPMiddleware` answers 400
  `INVALID_ORIGIN_SIGNATURE` to unverifiable origin headers instead of attributing them to the BFF. Used by
  `audit.log.client_ip` and every throttle (`apps/core/throttles.py`). Shared vectors:
  `apps/core/tests_fixtures/origin_signature_vectors.json` (asserted by Django and Vitest); real-server check:
  `ci/integration/run.sh`. No CORS is needed: the browser only talks to the BFF (docs/frontend-plan.md §3.1).
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
  **(Amended 2026-10-21: the code is logged only when `DEBUG`; production logs are shipped and
  retained, so they get a warning without the code.)**
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
- 2026-10-21  Signup with email verification, end to end: address-bound verification token checked
  under a row lock and carried in the URL fragment; three account-/address-bound delivery tasks on a
  shared `_deliver` helper (explicit result; welcome recorded only when sent); always-queued resend
  with a per-email throttle; staff-creation verification queued on commit; Django admin "Send
  verification email" / "Mark email verified" actions, read-only `email_verified`, `language_code` on
  the add form, and audited email changes that reset verification and bump `auth_version`. Frontend:
  `/signup` (`SignupForm`), `/verify-email` (`VerifyEmail`), `CheckEmailPanel` /
  `ResendVerificationPrompt`, resend on `EMAIL_NOT_VERIFIED` login, "Start free trial" link behind
  `SIGNUP_ENABLED`, profile verification badge, `ApiError.code`. Tests:
  `apps/accounts/tests/test_email_verification.py`, `SignupForm` / `VerifyEmail` /
  `LoginForm.verification` component tests, `proxy.test.ts`. Review fixes: the admin "send" action
  audits before it enqueues (broker failure → `user.verification_email_queue_failed`); one-argument
  pre-deploy welcome jobs are dropped; editing the login email withdraws the resend offer.
- 2026-10-21  Optional email code login: `OtpCode.channel` + index (migration `accounts.0008`),
  channel-aware row-locked `otp.issue` / `otp.verify`, `send_login_code_task` (worker-side code
  generation, eager-safe retries), `send_login_code_email` (gettext + `ngettext` expiry, en/te),
  `POST /auth/otp/email/request/` + `/auth/otp/email/verify/`, `OtpEmailThrottle`, phone OTP code no
  longer logged outside `DEBUG`. Frontend: `app/api/auth/login-email-otp` BFF handler,
  `requestEmailOtp` / `loginEmailOtp`, `features/auth/EmailCodeLogin.tsx` in the Owner and Staff login
  views, strings in all five catalogs, regenerated `api-schema.d.ts`. Tests:
  `apps/accounts/tests/test_email_otp.py`, `EmailCodeLogin.test.tsx`, `bff.test.ts`. ERD regenerated.
- 2026-10-20  GCP deployment readiness: trusted client IP (`apps/core/net.py`, `ClientIPMiddleware`, throttles);
  dedicated `JWT_SIGNING_KEY` (`SIMPLE_JWT['SIGNING_KEY']`, required in prod); `bootstrap_platform` (initial
  Super Admin, audited, idempotent); `check_db_roles`; health probes; IAP check on `/admin/`. See
  docs/deployment.md. Tests: `core/test_net.py`, `core/test_deployment.py`.
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
- 2026-10-19  Website contact form: `ContactMessage` model (`core.0007`, platform-level), public write-only
  `POST /api/v1/public/contact/` (serializer allow-list, honeypot, per-IP + per-email throttles, 16 KiB
  body cap, `CONTACT_MAX_BODY_BYTES`), `ContactMessageAdmin` (read-only inbox, audited mark-handled/new
  and delete). `core.throttles`, `core.exceptions.PayloadTooLarge`. Exempt from the app-client gate via
  the `/api/v1/public/` prefix. Tests: `apps/core/test_contact.py`. ERD regenerated.
- 2026-10-18  Platform support contacts: `PlatformConfig.support_email|support_phone|support_whatsapp|
  support_website|support_hours` (all blank by default, `core.0006`), edited by a Super Admin in Django
  admin. `GET /api/v1/support/` (public, no auth, `Cache-Control: public, max-age=300`) returns
  `{email, phone, whatsapp, whatsapp_url, website, hours}`; unset channels are `null`; `whatsapp_url` is
  `https://wa.me/<whatsapp>`. Phone/WhatsApp are digits with country code and no `+` (8–15 digits, admin
  validated) so toll-free numbers work. The endpoint is exempt from the app-client 426/503 gate
  (`devices.middleware.EXEMPT_PREFIXES`) so an outdated build or a maintenance window can still show it.
  Read with `filter(pk=1).first()`, never `PlatformConfig.get()`, so a public GET never writes.
  Tests: `apps/core/test_support.py`. These are platform-wide contacts, not per-property/PG contacts.
