# Module: Account Deletion

> Keep this file in sync with the code AT ALL TIMES.
> If the code and this file disagree, this file is wrong — fix it in the same commit.

**Status:** In Progress (backend + web done; Flutter "Delete account" entry is the open release blocker, see below)
**Phase:** 3 (Google Play requirement, 2026-10-23 — not in PRD v2)
**PRD reference:** PRD §4 "Deleted accounts" (superseded for self-service deletion, Decision 2)
**Depends on:** 01 (users, OTP, JWT auth), 13 (Razorpay ledger, `status_hold`), 14 (notifications), 15 (audit log), 19 (app installations)
**Blocks:** none. A future resident account type (docs: "Resident Passport" idea) must add its own rows to `DISPOSITION`.
**App:** `apps.accounts` (`deletion.py`), with changes in `apps.core`, `apps.subscriptions`, `apps.audit` consumers, and the Next.js frontend.

## Purpose
Google Play requires an app that creates accounts to let people delete them (a) inside the app and
(b) from a public web page that names the app and developer, and to delete the data (keeping only what
law requires, disclosed). This module lets an **Owner**, **Manager** or **Receptionist** request deletion,
locks the account at once, and lets a **00:00 IST beat task** purge it after a grace period unless it is
cancelled. An Owner's request deletes the **whole business** (tenant); a staff member's only themselves.

## Lifecycle
```
POST /auth/account/deletion/  ─►  pending ──(grace over, 00:00 IST run)──►  processing ──►  completed
                                    │  ▲                                        │
                  DELETE (cancel) ◄─┘  └── admin "retry now" ◄── failed ◄───────┘ (after N failed nights)
                                    ▼
                                cancelled            (superseded: a staff request when its Owner's business is purged)
```
`ACTIVE = pending | processing | failed`. An ACTIVE request **locks** the account (and, for an Owner's
request, every user of the business). `failed` is deliberately active: a purge that gave up is not a purge
that finished.

## Data model (as-built)
```
Table: account_deletion_requests          (apps.accounts; NOT under RLS — read before any tenant context exists)
  id UUID, user FK→users SET_NULL, tenant FK→tenants SET_NULL, scope (user|tenant)
  status: pending | processing | completed | cancelled | failed | superseded
  requested_at, scheduled_for     = requested_at + grace_days × 24h, rounded UP to the next 00:00 IST
  next_attempt_at                 retry pacing; starts = scheduled_for
  claimed_at, claim_token         the lease
  notified_at, notice_channel     (email | sms | none)
  razorpay_closed_at, db_purged_at, files_purged_at, completed_at, cancelled_at   phase stamps
  attempts, last_error (phase + exception class, never PII), reason (≤500, scrubbed on every exit from pending)
  UNIQUE(user)   WHERE status IN (pending, processing, failed)
  UNIQUE(tenant) WHERE scope='tenant' AND status IN (pending, processing, failed)

users:                 + UNIQUE(tenant) WHERE role='owner' AND is_active   (one Owner per business; migration pre-checks)
tenants.status:        + 'deleted'   (set only by the purge's last phase)
otp_codes:             + purpose (login | account_deletion)
platform_config:       + account_deletion_grace_days (default 7, ≥1), account_deletion_max_attempts (default 5, ≥1)
subscriptions.status_hold: + 'deleted'   (permanent; see rule 14)
subscription_payments: + refund_status (none|pending|refunded|waived), refund_flagged_at, refund_resolved_at,
                         refund_reference (rfnd_…), refund_resolution (code) — all structured, no free text;
                         CHECK constraint `payment_refund_state_valid` defines every valid combination
```
Migrations: `accounts.0009` (model, OTP purpose, `deleted` status, one-Owner index with a duplicate pre-check),
`accounts.0010` (seeds the nightly `PeriodicTask`), `core.0008` (config), `subscriptions.0015` (refund fields →
back-fill from legacy `subscription.payment_needs_refund` audit rows under the super-admin RLS context → constraint last).

## API endpoints (all under `/api/v1/`)
```
GET    /auth/account/deletion/        the ACTIVE request locking this account (own, or the business's); 404 if none
POST   /auth/account/deletion/        request.  Owner ⇒ scope=tenant; Manager/Receptionist ⇒ scope=user;
                                      Super Admin/Resident ⇒ 403. Body: password | otp, confirm=true, reason?
                                      → 201 {deletion, access, refresh}  (a fresh token pair: the request ends every session)
POST   /auth/account/deletion/otp/    emails a deletion-purpose code (202). Phone codes ⇒ 400 while there is no SMS backend
DELETE /auth/account/deletion/        cancel (204): the requester, or the business's Owner; 409 unless still pending
GET    /auth/me/                      + deletion {scope,status,scheduled_for,can_cancel}|null, deletion_confirm_methods[]
```
Throttles: `account_deletion` 5/hour (POST only), `account_deletion_otp` 3/min.
Lock error codes (HTTP **403**, not 401 — the session is fine): `ACCOUNT_DELETION_PENDING` (the requester),
`TENANT_DELETION_PENDING` (staff of a business whose Owner requested deletion).

## Business rules (each maps to a test)
Tests: `apps/accounts/tests/test_account_deletion.py`, `test_account_deletion_purge.py`,
`apps/subscriptions/tests/test_account_deletion_billing.py`; frontend under `features/account-deletion/__tests__`,
`lib/__tests__/api.deletionLock.test.ts`, `app/api/__tests__/bff.test.ts`.

1. **Grace** is `PlatformConfig.account_deletion_grace_days` (invariant 10), as full 24h days from the request,
   rounded *up* to 00:00 IST — a request at 23:59 is never purged after six days.
2. **Confirmation** needs the password or a deletion-purpose emailed code. OTPs are bound to a purpose: a login
   code cannot confirm a deletion, nor a deletion code log in. SMS is unavailable (`otp.sms_delivery_available`).
3. **Lock** (`TenantJWTAuthentication`): while ACTIVE only `(auth-me, GET)` and `(auth-account-deletion, GET|DELETE)`
   work, matched on route name + method (so `PATCH /auth/me/` is blocked). Requesting bumps `auth_version` (all
   sessions of the account — of the whole business for an Owner — end).
4. **Login/refresh** skip the "tenant suspended" rejection when an ACTIVE request exists, via the one shared
   `active_deletion_for()` used by JWT auth, password/OTP login and refresh. The tokens are still limited by rule 3.
5. **Cancel**: requester or the business's Owner, only while `pending`. Staff cannot cancel an Owner's request.
6. **Irreversibility**: `razorpay_closed_at` (tenant) / `db_purged_at` (user) is the point of no return. A Super
   Admin can *resolve as cancelled* only before it; afterwards the only recovery is retry-to-completion.
7. **Purge phases** (resumable; each stamps itself and runs under the lease): `notify` → `razorpay_close` (tenant)
   → `db_purge` → `files_purge` (tenant) → `complete`. `Tenant.status=DELETED` is set only in `complete`, after every
   login is gone, so the pending/failed screens stay reachable until then.
8. **Inventory** (`deletion.DISPOSITION`): every model says what a tenant purge and a staff purge do (purge /
   redact / retain / platform / self); a test fails if a model is missing, so future modules cannot forget.
9. **Staff purge** deletes the login and its personal rows; business records they created stay with the user FK
   nulled. Audit: IPs of actions they performed are cleared, and rows whose before/after names their id, email or
   phone are redacted **by value**, so legacy rows (e.g. property-staff assignments) are covered.
10. **Tenant purge** deletes every `TenantModelMixin` model in `PURGE_ORDER` (children before PROTECT parents),
    the tenant's audit log, users, installs, contact-form messages from their addresses, and the four storage
    prefixes (`residents|properties|complaints|expenses/<tenant_id>/`). **Retained** (tax records): `Tenant` (legal
    name only), `Subscription`, `RazorpaySubscription`, `SubscriptionInvoice(+Line)`, `SubscriptionPayment`,
    `BedLedgerEntry`; their Razorpay payloads are redacted to an allow-list of scalars
    (`subscriptions.services.sanitized_payload`), including legacy invoice events stored with `tenant_id=NULL`.
11. **Durability**: one claim (`deletion.claim`) for the beat task, admin and tests — a row lock + lease token,
    reclaimed after 15 minutes without a heartbeat. The files phase streams (lists one directory, deletes it, moves on — nothing larger than one listing is in memory) and heartbeats every 100 objects / 60 s **and around every directory listing**, so a slow listing can't outlast the lease and a worker that lost it stops at the next listing. `claim()` also clears `reason` atomically.
12. **Retry pacing**: a failure sets `next_attempt_at` to the next midnight IST, the task works from a snapshot of
    ids, so a request is attempted once per run; after `account_deletion_max_attempts` nights it is `failed`
    (logged `account_deletion_failed`, Super Admins emailed, listed in admin).
13. **Notice**: published (not `enqueue`d — a broker outage must stop the purge) before any data is removed,
    best-effort delivered, the address only ever in the Celery message. Phone-only users get none
    (`notice_channel='none'`).
14. **Razorpay tombstone**: `razorpay_close` invoices per-bed arrears (rule 28), moves live ledger rows to
    REPLACED/ABANDONED (cancelled by the existing 10-minute queue), sets `plan=None` and `status_hold='deleted'`.
    The hold is checked **before** non-current reconciliation, so a late charge is recorded (sanitized) and flagged
    for refund but can never promote a subscription, restore a plan or change the tenant. It is immutable: suspend,
    reactivate, plan selection, limit overrides and the Tenant/Subscription admin all refuse it. Neither `Tenant.status='deleted'` nor `status_hold='deleted'` can be entered by hand: the Tenant admin form doesn't offer `deleted` and refuses it on save, and `Subscription.status_hold` is read-only in admin.
15. **Refunds** are `SubscriptionPayment.refund_status='pending'` on the retained row, not only an audit row.
    Invoice payments for an arrears invoice are ours to keep (no refund). `payment.failed` stores only a sanitized event.
16. **Exit invoice**: new cycle invoices stop (no plan) but `process_invoice_issuing` is unchanged, so a final
    arrears invoice whose first Razorpay call failed is still sent later.
17. **Isolation**: purging tenant A leaves tenant B's rows, files and webhook events untouched.

## Permissions
Self-service roles: `owner`, `manager`, `receptionist` (by `user.role`, never by a missing tenant — a future
tenant-less resident must not be mistaken for a Super Admin). Super Admins use Django admin: *Account deletion
requests* (read-only; actions **Retry now** — failed or already-due only, it must not skip the grace period —
and **Resolve as cancelled**, needing a note), and the User action **Create account deletion request
(identity verified)** for an Owner who cannot sign in because the business was suspended.

## Edge cases handled
- Two simultaneous requests / an Owner and a staff request: the partial unique indexes decide (409);
  pending staff requests are `superseded` by the tenant purge; a `processing` staff request is left to finish
  (both purges are idempotent — an already-gone user counts as done).
- Tenant suspended *during* the grace period: the Owner can still sign in to view/cancel (rule 4) — by password, by
  emailed login code (`tasks._can_use_email_login` uses the same `active_deletion_for` exception) and by refresh.
- Tenant already suspended: the Owner cannot sign in; `/delete-account` shows the support contacts and a Super Admin
  can create the request on their behalf.
- Worker crash mid-phase: lease expiry → next run resumes at the first unstamped phase.
- GCS failure after the database purge: `db_purged_at` stays stamped; the rerun only deletes files.
- Outdated mobile build / maintenance mode: the app-client gate still applies to these routes; the public
  `/delete-account` web page is the fallback.

## Frontend
- `app/(marketing)/delete-account` — the public page for Play's "Delete account URL" (names the app and developer
  via `getSiteConfig`, what is deleted and kept, the wait, a "Sign in to delete" button, support contacts).
  Linked from the footer; added to the sitemap, the proxy's public allow-list and the service-worker marketing list.
  **The "at least 7 days" wording is static copy: update `marketing.legal.deleteAccount` if the config changes.**
- `(owner)/profile` — `DeleteAccountCard` (danger zone → dialog: what goes, export hint for Owners, acknowledge,
  password or emailed code).
- `app/account/deletion-pending` — its own top-level route with **no portal layout** (that layout's nav and queries
  are the calls that answer 403 while locked). Shows pending / processing / failed; cancel only when `can_cancel`.
- `lib/api.ts` — `handleForbidden()`: a 403 with a deletion code keeps the session and goes to the pending route
  (guarded against loops); every other 403 behaves as before. `postLoginRoute()` sends a locked account there after login.
- BFF — `POST /api/auth/request-account-deletion` (new route handler) installs the replacement token pair; the
  generic proxy refuses `POST auth/account/deletion` (method-aware `isTokenIssuingPath`) but forwards GET/DELETE.
- en + te strings: `messages/*/accountDeletion.json`, `marketing.json` (`legal.deleteAccount`, `meta`, `footer`).

## Open questions / Decisions
**Owner decisions (2026-10-23)**
1. Owner deletion = the whole tenant. Staff deletion = that user only.
2. Grace 7 days, configurable, ≥1. Supersedes PRD §4's "retained 30 days" for self-service deletion.
3. Platform billing is retained; the tombstone `Tenant` keeps only the legal name (tax counterparty).
4. Razorpay is cancelled at purge, not at request (renewals during the grace period are normal charges).
5. A charge after deletion is recorded and flagged for manual refund; it never reactivates anything.
6. Per-bed arrears at purge follow rule 28 (deletion is a plan exit).

**Judgement calls**
- `Tenant.Status.DELETED` is a new status (only the purge sets it); added to `BLOCKED_TENANT_STATUSES`.
- The lock is a 403, not a 401, so the generic client/BFF do not treat it as a dead session and refresh-loop.
- Staff `reason` and `last_error` hold no PII by construction (class + phase names) and `reason` is cleared the moment the purge claims the request (and on every other exit from pending).
- `retry_now` is refused for a request still inside its grace period.
- The nightly run logs open refund count and failed requests so neither stays invisible.
- Platform-level audit `account.deleted` carries only the request id and scope.
- `account_deletion_requests` has a `tenant_id` but no RLS (the login/refresh lock check and the nightly scan read it
  with no tenant context), so it is listed in `RLS_EXEMPT_TABLES` (`check_db_roles`) next to `users`.

**[OPEN] before this module is ✅**
- **Flutter** must ship Settings → "Delete account" (at minimum opening the web flow); Play's in-app requirement is
  not met by the web alone. Integration notes: `docs/auth-staff-flutter-integration.md` §10. README stays 🟨 until then.
- **Accounting**: confirm the retained set (legal name, amounts, dates, Razorpay ids) satisfies GST record rules.
- **Alerting**: create the Cloud Monitoring log-based alert on `account_deletion_failed` (`docs/deployment.md`).
- **SMS**: with no SMS backend, phone-only staff confirm by password and receive no notice.
- **Resident Passport** (separate idea): its tables need `DISPOSITION` entries and an `app.user_id` RLS context in
  the purge; as a later module its number should be 23.

## Changelog
- 2026-10-23  Module created: request/cancel API with OTP purpose binding and a method-aware lock; durable, resumable
  purge with leases, retry pacing and a data inventory guard; Razorpay tombstone (`status_hold='deleted'`), structured
  refund obligation, payload sanitizing; Django admin queue and actions; web UI (profile card, pending screen, public
  `/delete-account` page, BFF handler); en + te strings.
- 2026-10-23  Review fixes: `deleted` can no longer be set by hand in Django admin (Tenant status, `status_hold`);
  the files purge streams and heartbeats during listing; `reason` cleared in `claim()`; emailed-code login honours the
  active-deletion exception for a suspended tenant; the periodic-task seed looks the crontab up by timezone; the
  deletion tests pin Razorpay to the local stub instead of relying on `.env`.
- 2026-10-23  `account_deletion_requests` added to `RLS_EXEMPT_TABLES`; its omission failed the first production
  `pglive-check-roles` run after `migrate`.
