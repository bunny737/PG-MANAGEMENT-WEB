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
  last_sync_seq (bigint), first_seen_at, last_seen_at (indexed)

Table: app_installation_history                (append-only)
  installation_id FK CASCADE, build_number, version_name, os_version, recorded_at

Table: app_version_policies
  platform, flavor                              UNIQUE together
  min_build, latest_build (>= min_build), latest_version, store_url
  release_notes JSON {locale: text}, soft_update_enabled
  maintenance_enabled, maintenance_message, maintenance_expires_at
  check_interval_seconds (default 21600), updated_by FK SET NULL, updated_at

push_subscriptions (Module 14) gained:  installation_id FK → app_installations NULL, SET NULL
```

## API endpoints (all under `/api/v1/`)
```
GET     /app/version-policy/?platform=&build=&version=&flavor=   public; never 426/503
POST    /devices/                                                optional auth; never 401
DELETE  /devices/{installation_id}/user/                         auth required; always 204
POST    /notifications/push-subscriptions/                       (existing) + optional installation_id
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
- Body ≤ 8 KB (`413`), strings length-capped, unknown keys ignored, DRF field-error shape.
- Throttles: 30/hour per `installation_id`, 120/hour per IP (`429` + `Retry-After`).

### DELETE /devices/{installation_id}/user/
Clears the link only if it is the caller's; unknown/other-owner installs are a
silent no-op; always `204`.

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
4. Exempt: `/api/v1/app/version-policy/`, `/api/v1/devices/`, `/admin/`,
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
tenant-isolation test (`test_link_is_tenant_safe…`) → `test_push_link.py`. Retention, reports, admin
(masking, audit, confirmation), seed command → `test_ops.py`.

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
- [OPEN] `push-subscriptions` links to any existing `installation_id` regardless of its owner (metadata only).

## Changelog
- 2026-10-08  Module created: models, 3 endpoints + push-subscriptions `installation_id`, middleware,
  admin + audit + adoption report, retention task, seed command, 96 tests.
