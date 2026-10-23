# Module: App Client (version policy, device registration, force-update)

> Keep this file in sync with the code AT ALL TIMES.
> If the code and this file disagree, this file is wrong — fix it in the same commit.

**Status:** Done
**Phase:** 3 (mobile support — owner request 2026-10-08, not in PRD v2)
**PRD reference:** none
**Depends on:** 01 (users), 14 (push subscriptions), 15 (audit log)
**Blocks:** none
**App:** `apps.devices`

## Purpose
Lets the Flutter app (and any future non-browser client) (1) ask the server
whether its build must/should update or whether maintenance is on, (2) report
the install (device/OS/app build) for adoption and support, and (3) be
blocked server-side with a stable code when its build is too old or the
platform is in maintenance.

Client-side how-to for the Flutter app: [../app-client-flutter-integration.md](../app-client-flutter-integration.md).

Limitation: builds released before this shipped (`0.1.0+1`) send no `X-App-*`
headers and have no gate — they cannot be force-updated by this mechanism.

## Data model (as-built)
All three tables are **platform-level: no `tenant_id`, no RLS** (the app
registers before login and a device can serve several tenants over time).
They hold no name/phone/email/location/advertising ID.

```
Table: app_installations                       (apps.devices)
  id (bigint), installation_id UUID UNIQUE
  user_id FK → users NULL, ON DELETE SET NULL   (deleting a user keeps the anonymous row)
  platform (android|ios), flavor (dev|prod), build_mode
  version_name, build_number, package_id        INDEX (platform, build_number)
  os_name, os_version, os_sdk_int NULL
  device_manufacturer, device_model, is_physical
  screen_width_px, screen_height_px, pixel_ratio
  locale, utc_offset_minutes, timezone_abbr, network_type
  push_permission, fcm_token NULL UNIQUE        (a token belongs to one install)
  secret_hash                                   (SHA-256 of the app-generated install secret; '' = unclaimed)
  last_sync_seq (bigint), first_seen_at, last_seen_at (indexed)

Table: app_installation_history                (append-only)
  installation_id FK CASCADE, build_number, version_name, os_version, recorded_at

Table: app_version_policies
  platform, flavor                              UNIQUE together
  min_build, latest_build (>= min_build), latest_version, store_url
  release_notes JSON {locale: text}, soft_update_enabled
  maintenance_enabled, maintenance_message, maintenance_expires_at
  check_interval_seconds (default 21600), updated_by FK SET NULL, updated_at

push_subscriptions (Module 14) gained:  installation_id FK → app_installations NULL, SET NULL,
                                        partial UNIQUE (one subscription per install)
app_installations.fcm_token is a diagnostic mirror only — push is delivered from push_subscriptions.
```

## API endpoints (all under `/api/v1/`)
```
GET     /app/version-policy/?platform=&build=&version=&flavor=   public; never 426/503
POST    /devices/                                                optional auth; never 401
DELETE  /devices/{installation_id}/user/?sync_seq=N              auth required; always 204 (400 on a bad sync_seq)
POST    /notifications/push-subscriptions/                       web clients; mobile should not call it (still accepted)
```
The app also sends `X-App-Platform`, `X-App-Version`, `X-App-Build`,
`X-App-Flavor`, `X-Installation-Id` on every request.

### GET /app/version-policy/
- `update_mode`: `build < min_build` → `force`; else `build < latest_build`
  and `soft_update_enabled` → `soft`; else `none`. Integers only.
- No policy row → 200, `update_mode: none`, null build/url fields, `maintenance.enabled: false`.
- `maintenance.enabled` is the *effective* value (flag set and not expired).
- Bad/missing params → 400 `{"platform": [...]}`.
- `Cache-Control: public, max-age=60`; the DB lookup is cached 60 s and
  invalidated immediately when a policy is saved/deleted.

### POST /devices/
- **Proof of possession.** `installation_id` is an identifier (it appears in
  headers and log lines), not a credential.
  - **The secret.** The app generates its own secret once, together with the
    `installation_id`: 32 random bytes, base64url-encoded. It keeps the secret
    in secure storage and sends it as `X-Installation-Secret` on **every**
    `POST /devices/`, including the first. The server stores only its SHA-256
    and never returns it, so a lost response can't lose it. Retrying a create
    with the same body and secret returns 200.
  - **Format.** 32–128 printable ASCII characters. Anything else gets
    `400 {"code":"INSTALLATION_SECRET_MALFORMED"}`.
  - **Install that has a secret.** The call must present it. A missing or wrong
    secret gets `403 {"detail","code":"INSTALLATION_SECRET_INVALID"}` and
    changes nothing: no link change, no subscription change, no `sync_seq`
    advance. The app then generates a new `installation_id` and secret and
    registers as a new install.
  - **Install without a secret** (`secret_hash=''`, registered by a build
    released before this change; those builds send no header and keep working
    this way). Only a stakeholder is served:
    - the authenticated linked user;
    - the authenticated owner of a push subscription on it;
    - anyone, when it has neither (nothing to take over).
  - **Claiming.** A stakeholder call that carries a secret claims the install
    with that secret and keeps the same `installation_id`. This also works on
    a stale-`sync_seq` call.
  - **Non-stakeholders on an install without a secret.**
    - Anonymous (for example, the owner's session expired): `200
      {"registered":true,"ignored":"unclaimed_install"}`, nothing changed.
      The app treats it like any other `ignored` response, and the next
      signed-in sync claims the install.
    - Authenticated (a different user signed in on this phone): the 403
      above, so the app starts a new install for that user.
  - The possession check runs before the stale-`sync_seq` check.
- Auth is optional: a missing/expired/invalid token — or a user of a suspended
  tenant — is treated as anonymous (`OptionalTenantJWTAuthentication`).
- User link: authenticated → `installation.user = request.user` (last writer
  wins); anonymous + `signed_in:false` → unlink; anonymous + `signed_in:true`
  → unchanged, response `user_linked:false`.
- `sync_seq` lower than stored → whole request ignored
  (`200 {"registered": true, "ignored": "stale_sync_seq"}`, logged); equal is
  reprocessed (idempotent retry).
- Upsert by `installation_id` (`201` create / `200` update). History row on
  first sighting and whenever `build_number` or `os.version` changes.
- A non-null `push.fcm_token` is nulled on every other install; a null/blank
  token clears the stored one (the body carries the full device state). Never logged.
- **Push subscription reconciliation** (create and update paths alike, same
  transaction as the install upsert). This is the app's only push registration call.
  - **Authenticated sync.**
    1. Drop every `PushSubscription` on this install owned by someone else
       (cross-tenant, super admin), so an account switch never leaves the
       previous user subscribed.
    2. Token present → upsert the caller's subscription (`device_type` =
       platform). Token null/blank → remove the caller's subscription on this
       install.
  - **Anonymous `signed_in:false` sync that proves possession** (matching
    `X-Installation-Secret`): remove **every** subscription on this install.
    This is the device itself after a forced or offline logout, so it must
    stop receiving the previous user's pushes even if `deleteToken()` failed.
  - **Untouched:** any other anonymous sync (`signed_in:true`, or no proof,
    e.g. an install from a build without secrets) and any stale `sync_seq`.
  - The response adds `push: {"subscribed": true|false|null}`, where `null`
    means not evaluated.
- Body ≤ 8 KB (`413`), strings length-capped, unknown keys ignored, DRF field-error shape.
- Throttles: 30/hour per `installation_id`, 120/hour per IP (`429` + `Retry-After`).

### DELETE /devices/{installation_id}/user/
Logout. In one transaction (install row locked): removes the caller's push
subscription on this install, then clears the link only if it is the
caller's; unknown/other-owner installs are a silent no-op; always `204`. The
app calls it best effort, **before** discarding its tokens, with whatever
access token it has. A 401 counts as done: the signed-out device sync that
follows removes the subscription anyway.

Optional `?sync_seq=N` and optional `X-Installation-Secret`. The app uses a
`sync_seq` value higher than any `POST /devices/` it has already sent: the
next value of the same persisted counter, whether or not the call goes
through the sync queue. The value is stored as `last_sync_seq` (never
lowered) only if the caller has a stake in the install:
- it is the install's linked user;
- a subscription of theirs on it was just removed;
- or it presents the install's secret (the device itself, even after a
  signed-out sync already removed everything).

This makes an authenticated `POST /devices/` that was already in flight
(lower seq) count as stale, instead of re-subscribing the logged-out device.
A caller without a stake can't advance it, so nobody can freeze another
device's syncs.

## Middleware (`AppClientMiddleware`)
1. Parses `X-App-*` leniently into `request.app_client` (`None` if nothing
   usable) — a malformed/missing header never fails a request.
2. Puts platform/version/build/flavor/installation_id into a context var used by
   `AppClientLogFilter` (every log line via the `app_console` handler in
   `LOGGING`) and into Sentry tags (`app.*`) when `sentry_sdk` is installed.
3. Enforcement, `APP_VERSION_ENFORCEMENT=off|log|on` (default `log`; unknown value ⇒ `off`):
   - maintenance active → `503 {"detail","code":"MAINTENANCE","message","expires_at"}` (+ `Retry-After`)
   - `X-App-Build < min_build` → `426 {"detail","code":"APP_UPDATE_REQUIRED","min_supported_build","store_url"}`
   - `log` mode logs "would block" warnings only.
4. Exempt: `/api/v1/app/version-policy/`, `/api/v1/devices/`, `/api/v1/support/` (Module 01), `/admin/`,
   `/static/`, `/media/`, `/health*`, plus `APP_VERSION_EXEMPT_PREFIXES`.
   Login/OTP/refresh are **not** exempt.
5. Requests with no usable `X-App-Platform` are never blocked (web, Postman, admin).
6. QA bypass of maintenance: `X-Maintenance-Bypass: <APP_MAINTENANCE_BYPASS_TOKEN>`
   (constant-time compare; disabled when the token is blank).

## Admin
- `AppVersionPolicy`: editable; every create/update/delete is written to the
  audit log (`app_version_policy.created|updated|deleted`, before/after, actor,
  IP; platform-level, readable as super admin); `updated_by` stamped;
  raising `min_build` requires ticking "Confirm raising min_build".
- `AppInstallation`: read-only (no add/change), `fcm_token` never rendered
  (masked `abcd…wxyz`), history inline, **Adoption report** page (active
  installs by build, below latest / below min per policy, top device models and
  OS versions — queries in `reports.py`, "active" = seen in last 7 days).
  Deleting runs as super admin because it nulls `push_subscriptions.installation`
  (RLS table).

## Operations
- `manage.py seed_app_version_policies --latest-build N [--latest-version V] [--android-store-url U] [--ios-store-url U]`
  creates the four (platform × flavor) rows with `min_build=1`; existing rows untouched.
- Retention (privacy), Celery beat task `devices.purge_stale_app_data` daily 03:30 IST (migration 0002,
  retimable in admin): installs unseen > `APP_INSTALLATION_RETENTION_DAYS` (180) and history older than
  `APP_INSTALLATION_HISTORY_RETENTION_DAYS` (365) are deleted.
- Env: `APP_VERSION_ENFORCEMENT`, `APP_MAINTENANCE_BYPASS_TOKEN`, `APP_VERSION_EXEMPT_PREFIXES`,
  the two retention vars.

### Rollout order
1. Deploy with `APP_VERSION_ENFORCEMENT=log`. 2. `seed_app_version_policies`.
3. Release the app build that calls these endpoints. 4. Watch the adoption report and "would block" warnings.
5. Switch to `on`; raise `min_build` only once the new build is fully live in the store (Play: staged rollout
finished; App Store: released, past review) — never above a build still in review/TestFlight.
6. CI must produce strictly increasing build numbers per platform and flavor.

## Business rules → tests (`apps/devices/tests/`)
Policy modes/no-row/bad params/maintenance/caching → `test_version_policy.py`. Register rules (anonymous/authed,
expired token, signed_in, sync_seq, token move, history, validation, size, throttles) → `test_register.py`.
Unlink (owner / non-owner / unknown) → `test_unlink.py`. Middleware (426/503 codes, plain 500, exempt paths,
garbage headers, off/log/on, login gated, bypass, fail-open) → `test_middleware.py`. Push link and the
tenant-isolation test (`test_link_is_tenant_safe…`) → `test_push_link.py`. Subscription reconciliation
(token present/null on create and update, rotation, token move, account switch incl. after an anonymous
unlink, anonymous/expired/malformed/suspended cannot remove, stale seq, rollback, isolation) and logout
removal → `test_push_reconcile.py`. Retention, reports, admin (masking, audit, confirmation), seed
command → `test_ops.py`.

## Privacy
- Tables hold no PII; `installation_id` + user link is personal data. **Add to the privacy policy.**
- User deletion: FK is `SET_NULL`, so the device row survives anonymously (as specified). There is no user
  deletion/export flow in the codebase yet; when one is built, include `app_installations` (by `user`) in it.

## Decisions
- [DECISION 2026-10-08] Owner asked to implement the app-client spec as-is (rev 3 rule: anonymous
  `signed_in:true` is accepted and leaves the link unchanged). This is a new cross-module schema change
  (new app + `push_subscriptions.installation`); owner's "implement whatever is required" taken as approval.
- [DECISION] New app `apps.devices` and module number 19; not in PRD v2 (same status as module 18).
- [DECISION] Platform-level tables have no RLS. `PushSubscription` stays tenant-scoped; the new FK is
  SET_NULL and any delete of installs must run in a super-admin tenant context (retention task + admin do).
- [DECISION] A history row is also written on first sighting (the spec says "when build/os changes"; the
  initial row is the funnel's starting point).
- [DECISION] A null/blank `push.fcm_token` clears the stored token (body is the full device state).
- [DECISION] `user_linked` in the response means "this request was authenticated", so an anonymous
  `signed_in:true` call on an already-linked install returns `false` while the link is kept.
- [DECISION] Staff maintenance bypass is a shared-secret header only, not an IP allowlist: behind a load
  balancer `REMOTE_ADDR` is the balancer and `X-Forwarded-For` is client-controlled.
- [DECISION] Enforcement fails open (cache/DB error ⇒ request proceeds, error logged). Unknown
  `APP_VERSION_ENFORCEMENT` values behave as `off`. Maintenance 503s are excluded from `django.request`
  error logging (`_has_been_logged`) so a planned outage doesn't flood Sentry.
- [DECISION] Retention windows are env settings, not `PlatformConfig` columns (not plan limits; avoids a
  core schema change). "12 months" = 365 days.
- [DECISION] `os.sdk_int` / `network_type` / `push.fcm_token` are nullable and may be omitted; every other
  key is required (spec: "all keys always present").
- [DECISION] Added a project-wide `LOGGING` config (WARNING+ for `apps.*`, ERROR for `django.request`) so log
  lines carry the app build; previously none was configured.
- [OPEN] Telugu/other-locale translations of the 426/503 `detail` strings (gettext-wrapped; `.po` entries not
  added — the app switches on `code`, not the text).
- [DECISION 2026-10-16] `POST /devices/` reconciles `PushSubscription` (Module 14's single delivery
  record), so mobile needs one registration call; only authenticated callers can remove subscriptions
  (see Module 14 Decisions for the accepted offline-logout gap).
- [DECISION 2026-10-16] `push-subscriptions` links an `installation_id` only if that install is already
  linked to the caller (otherwise ignored, like an unknown id). Linking replaces the install's
  subscription as super admin, so a bare UUID would have let anyone unsubscribe another device.
- [DECISION 2026-10-16] Logout takes optional `sync_seq` and joins `POST /devices/` ordering (see above).
- [DECISION 2026-10-16] **Per-installation secret** (owner approved; client contract change).
  Installation UUIDs are identifiers, not credentials. Before this, anyone who learned another
  device's `installation_id` could take over its link and drop its push subscription across tenants:
  first an anonymous `signed_in:false` sync to clear the link, then an authenticated one. That
  anonymous unlink is required for forced logout, so only proof of possession closes it.
  - Only the hash is stored (SHA-256 suffices for a 256-bit random secret), compared in constant
    time, never logged, and excluded from admin.
  - **The app generates the secret** (decided after the Flutter team's review; the server minted
    it in an earlier draft). A server-minted secret travelled in a response. That meant:
    - a lost first response orphaned the install;
    - the app had to store the secret before any `ignored` early return;
    - older builds discarded it, locking nearly every upgraded install out.

    Now the app owns it from the start, and builds that send no secret keep working secret-less.
  - An install without a secret only serves a stakeholder (its linked user, or the owner of a
    subscription on it), or anyone if it has neither. Plain trust on first use was rejected in
    review: a cross-tenant caller could claim a linked install and, in the same call, relink it and
    drop the owner's subscription.
  - A non-stakeholder anonymous call on such an install gets `ignored: unclaimed_install`, not a 403.
    The owner's own expired-session sync must not push the app into abandoning a good
    `installation_id`.
  - Logout (`DELETE /devices/{id}/user/`) needs no secret. It only acts for a caller with a stake
    in the install (its linked user, or the owner of a subscription on it).

## Changelog
- 2026-10-08  Module created: models, 3 endpoints + push-subscriptions `installation_id`, middleware,
  admin + audit + adoption report, retention task, seed command, 96 tests.
- 2026-10-16  `POST /devices/` reconciles the push subscription (response gains `push.subscribed`);
  logout also removes the caller's subscription. `test_push_reconcile.py` (19 tests).
- 2026-10-16  Review fixes: logout `?sync_seq` (rejects in-flight registrations after logout, row lock);
  push-subscriptions `installation_id` must belong to the caller. Docker: `./secrets` mounted read-only
  at `/run/secrets` for the Firebase credential; test runs blank Firebase credentials. 6 new tests.
- 2026-10-16  Per-installation secret: `AppInstallation.secret_hash` (migration 0003), `X-Installation-Secret`
  required on `POST /devices/` for existing installs (403 `INSTALLATION_SECRET_INVALID`), secret returned
  once as `installation_secret`. Logout stores `sync_seq` also when the caller's subscription was removed
  after an anonymous unlink. `test_installation_secret.py` (8 tests) + 1 logout regression.
- 2026-10-16  Legacy installs are claimable only by a stakeholder (linked user / subscription owner) or
  when unowned; 4 regression tests incl. cross-tenant legacy claim.
- 2026-10-16  Secrets are minted only for builds sending `X-Installation-Secret-Support: 1` (Flutter team
  review: older builds sync daily and would claim and discard the secret, pushing nearly every upgrade into
  the 403 / new-`installation_id` path). Older builds keep working secret-less under the stakeholder rule;
  upgrades claim cleanly. `OlderBuildTests` (4 tests).
- 2026-10-16  Secret is now **app-generated**, sent on every call including the first; the server never
  returns it, and the `X-Installation-Secret-Support` header is gone. Format check (400 `MALFORMED`). An
  anonymous non-stakeholder on an unclaimed install gets `ignored: unclaimed_install` instead of a 403.
  `test_installation_secret.py` rewritten (15 tests).
- 2026-10-16  Flutter team review 3:
  - An anonymous `signed_in:false` sync that proves possession (its secret) removes every subscription on
    the install. This closes the forced/offline-logout gap without relying on `deleteToken()`.
  - Logout accepts `X-Installation-Secret` as a stake, to advance `sync_seq`.
  - The logout `sync_seq` only needs to exceed the app's earlier POSTs; a sync queue is not required.
  - A test confirms that a previous user's FCM token moves to the new user's fresh install.
  - Builds without secrets: their anonymous syncs on a linked install are now answered
    `ignored: unclaimed_install` and no longer clear the diagnostic user link.
