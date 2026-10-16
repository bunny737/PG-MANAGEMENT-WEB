# Flutter integration guide — app version policy, device registration, force-update

> Companion to [modules/19-app-client.md](modules/19-app-client.md) (backend spec, the source of truth) and
> [push-notifications-integration.md](push-notifications-integration.md) (FCM setup). This doc is the practical
> *how* for the Flutter app. All paths are under `{BASE_URL}/api/v1/`.

## 0. TL;DR — what the app must do

1. Send five `X-App-*` / `X-Installation-Id` headers on **every** request (§2).
2. On launch and on resume, call `GET /app/version-policy/` and act on `update_mode` / `maintenance` (§3).
3. Call `POST /devices/` to report the install on launch, on login, on logout, and when the FCM token / push
   permission / app build / OS version changes (§4). Generate an install secret once (secure storage) and send
   it as `X-Installation-Secret` on every `POST /devices/` (§4.5).
4. Call `DELETE /devices/{installation_id}/user/` on logout, **before** discarding tokens (§5).
5. Push registration is part of `POST /devices/`: an authenticated call with `push.fcm_token` subscribes the device.
   Do **not** also call `push-subscriptions` (§6).
6. Treat **only** two server responses as blocking: `426` + `code: APP_UPDATE_REQUIRED` and `503` + `code: MAINTENANCE` (§7).

Builds released before this feature (`0.1.0+1`) send no headers and **cannot** be force-updated. Only builds that
include this work can.

## 1. Packages

`dio`, `package_info_plus`, `device_info_plus`, `uuid`, `shared_preferences` (or `flutter_secure_storage`),
`connectivity_plus`, `firebase_messaging` (already used for push).

## 2. Headers on every request

| Header | Value |
|---|---|
| `X-App-Platform` | `android` or `ios` (lowercase) |
| `X-App-Version` | `PackageInfo.version`, e.g. `1.2.0` |
| `X-App-Build` | `PackageInfo.buildNumber` — **integer** string, e.g. `12` |
| `X-App-Flavor` | `dev` or `prod` |
| `X-Installation-Id` | the install UUID (§2.1) |

The server parses these leniently — a bad header never breaks a request — but a missing/invalid
`X-App-Platform` or `X-App-Build` means that request cannot be gated, so always send valid values.

### 2.1 Installation id
Generate a UUID v4 **once** on first launch, persist it, and never regenerate it (uninstall/reinstall gives a new
one; that is expected). It is personal data when combined with a signed-in user — don't log it to third parties.

### 2.2 Build numbers
The server compares **integers only** (`X-App-Build`), never version strings. CI must produce strictly increasing
build numbers per platform and flavor (`pubspec.yaml` `version: 1.2.0+12` → build `12`).

### 2.3 Dio setup

```dart
class AppClientInterceptor extends Interceptor {
  AppClientInterceptor(this.info);
  final AppClientInfo info; // loaded once at startup

  @override
  void onRequest(RequestOptions options, RequestInterceptorHandler handler) {
    options.headers.addAll({
      'X-App-Platform': info.platform,        // 'android' | 'ios'
      'X-App-Version': info.versionName,      // '1.2.0'
      'X-App-Build': info.buildNumber.toString(),
      'X-App-Flavor': info.flavor,            // 'dev' | 'prod'
      'X-Installation-Id': info.installationId,
    });
    handler.next(options);
  }
}
```

Add it to the same `Dio` instance that does auth (including the login/refresh calls — those are gated too, so an
old build is stopped at login).

## 3. `GET /app/version-policy/`

Public (no auth; a bad token is ignored). Call it:
- on cold start, **before** showing the login/home screen;
- on app resume if more than `check_interval_seconds` has passed since the last successful check;
- you may also re-check after a `426`/`503`.

```
GET /api/v1/app/version-policy/?platform=android&build=12&version=1.2.0&flavor=prod
```

| Query | Required | Notes |
|---|---|---|
| `platform` | yes | `android` \| `ios` |
| `build` | yes | integer ≥ 0 |
| `version` | no | informational |
| `flavor` | no | `dev` \| `prod`, default `prod` |

**200 response**
```json
{
  "update_mode": "none",
  "min_supported_build": 10,
  "latest_build": 14,
  "latest_version": "1.3.0",
  "store_url": "https://play.google.com/store/apps/details?id=com.pgmate.app",
  "release_notes": { "en": "Bug fixes", "te": "..." },
  "maintenance": { "enabled": false, "message": null, "expires_at": null },
  "check_interval_seconds": 21600,
  "server_time": "2026-10-08T10:00:00Z"
}
```

How to act:

| Field | Behaviour |
|---|---|
| `update_mode = "force"` | Block the app with a non-dismissible "Update required" screen; button opens `store_url`. |
| `update_mode = "soft"` | Show a dismissible "Update available" prompt (remember the dismissal per `latest_build`). |
| `update_mode = "none"` | Carry on. |
| `maintenance.enabled = true` | Show a maintenance screen with `message`; if `expires_at` is set, show/auto-retry after it. |

Notes:
- If the server has no policy for this platform/flavor it still returns **200** with `update_mode: "none"`,
  `maintenance.enabled: false`, and `null` for `min_supported_build`, `latest_build`, `latest_version`, `store_url`
  (`release_notes` is `{}`). Handle the nulls.
- `release_notes` is keyed by locale — pick the user's language (`en`, `te`, …) and fall back to `en`.
- `maintenance.enabled` is already "effective" (an expired window comes back `false`).
- This endpoint **never** returns 426 or 503, even during maintenance — maintenance arrives as `200` with the flag.
- If the call itself fails (network, 5xx), **fail open**: let the user in. The server gate (§7) is the safety net.
- The response is cacheable for 60 s (`Cache-Control: public, max-age=60`); don't poll faster than that.
- Use `server_time` rather than the device clock when comparing against `maintenance.expires_at`.
- `400 {"platform": ["…"]}` means a bad/missing query param (a bug in the app, not a runtime condition).

## 4. `POST /devices/` — register / refresh this install

Reports device and app info for the install. **Auth is optional**: send `Authorization: Bearer <access>` if you
have one, but **do not refresh an expired token for this call** and don't retry on 401 — this endpoint never
returns 401; an expired/invalid/missing token is simply treated as anonymous.

### 4.1 When to call
- App launch (after the headers/installation id are ready).
- Right after login succeeds (authenticated, `signed_in: true`) — this links the user to the install.
- On logout (see §5) and on any forced logout / session expiry: send `signed_in: false` (anonymous) so the server
  unlinks the user even if the token is already dead.
- When any of these change: FCM token, push permission, app build, OS version, locale.
- **Not** on every screen or request: the budget is **30 requests/hour per install and 120/hour per IP**
  (`429` + `Retry-After`). Debounce, and on `429` simply wait for `Retry-After`.

### 4.2 Request body
All keys must be present except those marked nullable (those may be `null` or omitted). Unknown extra keys are ignored.
Body must be **≤ 8 KB** (`413` otherwise).

```json
{
  "installation_id": "uuid-v4",
  "sync_seq": 42,
  "signed_in": true,
  "platform": "android",
  "flavor": "prod",
  "build_mode": "release",
  "app": { "version_name": "1.2.0", "build_number": 12, "package_id": "com.pgmate.app" },
  "os": { "name": "Android", "version": "14", "sdk_int": 34 },
  "device": { "manufacturer": "samsung", "model": "SM-S918B", "is_physical": true },
  "screen": { "width_px": 1080, "height_px": 2340, "pixel_ratio": 2.6 },
  "locale": "te-IN",
  "utc_offset_minutes": 330,
  "timezone_abbr": "IST",
  "push": { "fcm_token": null, "permission": "granted" },
  "network_type": "wifi"
}
```

| Field | Type / limits | Notes |
|---|---|---|
| `installation_id` | UUID | same value as the `X-Installation-Id` header |
| `sync_seq` | int, 0 … 2^53 | **see §4.3** |
| `signed_in` | bool | does the app currently believe a user is logged in? |
| `platform` | `android` \| `ios` | |
| `flavor` | `dev` \| `prod` | |
| `build_mode` | string ≤ 16 | `debug` / `profile` / `release` (`kReleaseMode` etc.) |
| `app.version_name` | string ≤ 64 | |
| `app.build_number` | int 1 … 2^31−1 | |
| `app.package_id` | string ≤ 128 | |
| `os.name`, `os.version` | string ≤ 64 | |
| `os.sdk_int` | int, nullable | Android SDK level; `null`/omit on iOS |
| `device.manufacturer`, `device.model` | string ≤ 64 | iOS: manufacturer `"Apple"`, model e.g. `iPhone15,2` (`utsname.machine`) |
| `device.is_physical` | bool | |
| `screen.width_px`, `height_px` | int ≥ 0 | |
| `screen.pixel_ratio` | number ≥ 0 | |
| `locale` | string ≤ 16 | e.g. `te-IN` |
| `utc_offset_minutes` | int −1440 … 1440 | `DateTime.now().timeZoneOffset.inMinutes` |
| `timezone_abbr` | string ≤ 16 | `DateTime.now().timeZoneName` |
| `push.fcm_token` | string ≤ 255, nullable | current token, or `null` |
| `push.permission` | string ≤ 32 | e.g. `granted` / `denied` / `not_determined` |
| `network_type` | string ≤ 32, nullable | `wifi` / `mobile` / … |

Do **not** send name, phone, email, location or advertising IDs — the backend stores none of them.

**`push.fcm_token` semantics:** the body is the *full* device state. A non-null token is moved to this install
(removed from any other install that held it); `null` clears the stored token. So always send the current token
when you have one.

**Push subscription.** This call is also how the device subscribes to push:
- valid token + `push.fcm_token` → the signed-in user is subscribed on this install (a rotated token replaces the
  old one);
- valid token + `push.fcm_token: null` (permission denied/revoked) → the user's subscription on this install is
  removed;
- any authenticated call also removes subscriptions on this install that belong to a *different* user, so an
  account switch never leaves the previous user receiving pushes;
- no/expired/invalid token + `signed_in: false` + the correct installation secret (§4.5) → **every** subscription
  on this install is removed. This is how a forced or offline logout stops the previous user's pushes, even if
  `deleteToken()` failed;
- any other anonymous call (`signed_in: true`, or no valid secret) never changes subscriptions.

### 4.3 `sync_seq` — ordering (important)
`sync_seq` is a counter stored **on the device** that increases by one for every `POST /devices/` the app makes
(persist it; it must survive restarts). The server ignores any request whose `sync_seq` is **lower** than the last
one it accepted, so a delayed request from an earlier session can never overwrite a newer one (e.g. a late
"signed in" arriving after the "signed out"). An **equal** value is processed again, so retrying the same request
after a timeout is safe — resend the same `sync_seq`.

Rules for the client:
1. Allocate the next `sync_seq` and persist it **before** sending.
2. Send device-registration calls through a single serial queue so they can't overtake each other.
3. On retry of a failed/timed-out call, reuse the same body and `sync_seq`.

```dart
class DeviceSync {
  DeviceSync(this._dio, this._prefs, this._info);
  final Dio _dio; final SharedPreferences _prefs; final AppClientInfo _info;
  Future<void> _tail = Future.value();

  /// Serialises calls; each one gets the next sync_seq.
  Future<void> sync({required bool signedIn, String? accessToken, String? fcmToken, required String pushPermission}) {
    return _tail = _tail.then((_) async {
      final seq = (_prefs.getInt('device_sync_seq') ?? 0) + 1;
      await _prefs.setInt('device_sync_seq', seq);
      try {
        await _dio.post('/devices/',
          data: await _buildBody(seq, signedIn, fcmToken, pushPermission),
          // Never refresh/retry on 401 here; just attach the token if we have one.
          options: Options(headers: {if (accessToken != null) 'Authorization': 'Bearer $accessToken'}));
      } on DioException catch (e) {
        if (e.response?.statusCode == 429) { /* honour Retry-After, try again later */ }
        // Other failures: ignore; the next launch/login will resync.
      }
    });
  }
}
```

### 4.4 Responses
| Status | Body | Meaning |
|---|---|---|
| `201` | `{"installation_id","registered":true,"user_linked":bool,"push":{"subscribed":bool\|null},"server_time"}` | first registration. `push.subscribed`: `true`/`false` after an authenticated call, `null` for anonymous (subscription left untouched) |
| `200` | same | updated |
| `200` | `{"registered":true,"ignored":"stale_sync_seq"}` | your `sync_seq` was older than the server's. **Not an error** — a newer call already won. No `user_linked` key. |
| `200` | `{"registered":true,"ignored":"unclaimed_install"}` | anonymous sync on an install not yet claimed with a secret (§4.5). Not an error; nothing changed. |
| `400` | DRF field errors, nested objects nest, e.g. `{"app":{"build_number":["…"]}}` | bug in the payload |
| `400` | `{"detail","code":"INSTALLATION_SECRET_MALFORMED"}` | `X-Installation-Secret` not 32–128 printable ASCII chars |
| `403` | `{"detail","code":"INSTALLATION_SECRET_INVALID"}` | missing/wrong secret, or another user on an unclaimed install — start over with a new `installation_id` + secret (§4.5) |
| `413` | `{"detail","code":"PAYLOAD_TOO_LARGE"}` | body > 8 KB |
| `429` | + `Retry-After` header | throttled |

`user_linked` means "this request carried a valid token". Rules the server applies:
- valid token → install is linked to that user (last writer wins, so switching accounts just works);
- no/expired/invalid token and `signed_in: false` → install is **unlinked** (this is how the server recovers from an
  offline logout, a session expiry, or a forced logout);
- no/expired/invalid token and `signed_in: true` → link left **unchanged**, `user_linked: false` (e.g. the token just
  expired — don't treat it as logout).

Also a suspended tenant's user is treated as anonymous here (no 401).

### 4.5 Installation secret (proof of possession)
`installation_id` is not secret, since it travels in every request header. So the app also keeps a private
per-install secret and sends it on every `POST /devices/`. The server stores only a hash and never sends it back.

- **Generating it.** The app generates it itself:
  - when it creates the `installation_id`;
  - on first launch of this build, if it already has an `installation_id` from an older build but no secret.

  Use 32 bytes from `Random.secure()`, base64url-encoded (about 43 characters). Store it in secure storage next
  to the `installation_id`, before the first request that uses it.
- **Sending it.** Send `X-Installation-Secret: <secret>` on **every** `POST /devices/`, including the first. A retry
  after a lost response just resends the same secret; the server accepts it.
- **Format.** 32–128 printable ASCII characters, or `400 INSTALLATION_SECRET_MALFORMED`.
- **Installs registered by older builds.** These have no secret yet. The first signed-in sync from this build
  claims the install with the app's secret and keeps the same `installation_id`.
- **`ignored: "unclaimed_install"`.** An anonymous sync (for example, an expired session) on an install that isn't
  claimed yet gets `200 {"registered":true,"ignored":"unclaimed_install"}`. Nothing to do, and the next signed-in
  sync claims the install. Do record it as a completed sync for throttling purposes (unlike `stale_sync_seq`).
  Otherwise every app start or resume resends it until the user signs in.
- **Unowned installs.** An install with no linked user and no push subscription can be claimed by whichever caller
  sends a secret first, because there is nothing to take over. If someone else claimed yours, your next sync gets
  the 403 below and the app starts a new install. That's harmless.
- **Read failures.** If reading the secret (or the `installation_id`) from secure storage throws, treat it as
  missing. Generate a new id and secret and keep going, rather than disabling device sync. On Android, consider
  excluding secure storage from Auto Backup: a restored copy can't be decrypted on another device.
- **On 403.** `403` with `code: INSTALLATION_SECRET_INVALID` means the server changed nothing. Either the secret is
  missing or wrong (for example, storage was restored or partly wiped), or a different user is signed in on an
  unclaimed install.
  1. Generate a **new** `installation_id` and a new secret.
  2. Reset `sync_seq`.
  3. Schedule a new sync **immediately**, so push doesn't stay unregistered until the next scheduled sync. Inside the
     serial sync queue, don't *await* the call that schedules it: if it returns the running sync loop, awaiting it
     there deadlocks. Mark the state dirty and queue another run instead.

  Don't retry with the same id.
- **Never log it.** Don't log it, and don't send it to analytics or crash reporting.

```dart
Future<String> installationSecret() async {
  var secret = await secureStorage.read(key: 'installation_secret');
  if (secret == null) {
    final bytes = List<int>.generate(32, (_) => Random.secure().nextInt(256));
    secret = base64Url.encode(bytes).replaceAll('=', '');
    await secureStorage.write(key: 'installation_secret', value: secret);
  }
  return secret;
}

final res = await _dio.post('/devices/', data: body, options: Options(headers: {
  if (accessToken != null) 'Authorization': 'Bearer $accessToken',
  'X-Installation-Secret': await installationSecret(),
}));
```

## 5. `DELETE /devices/{installation_id}/user/` — logout

Requires `Authorization: Bearer <access>`. Call it **before discarding the tokens** during logout. It's best effort:
send the access token you have, and don't refresh it just for this call. If it has expired the call gets 401; treat
that as done (the subscription is then cleaned up as in the forced-logout case below). It removes the caller's push
subscription on this install and clears the user link if the install belongs to the caller; unknown ids and other
users' installs are a silent no-op. **Always `204`** (so it never reveals ownership); idempotent.

Logout sequence:
1. Take a `sync_seq` **higher than every `POST /devices/` already sent**: the next value of the same persisted
   counter as §4.3. Taking it inside the sync queue or from a shared counter both work.
2. Call `DELETE /devices/{installation_id}/user/?sync_seq=<that value>` with the access token and
   `X-Installation-Secret`. This stops the device receiving the old user's pushes. The `sync_seq` makes the server
   ignore any authenticated `POST /devices/` that was still in flight, which would otherwise re-subscribe the
   device. The secret lets the server record that `sync_seq` even when nothing else ties the caller to the
   install.
3. Clear local tokens/session and call `FirebaseMessaging.instance.deleteToken()`.
4. `POST /devices/` with `signed_in: false`, no `Authorization` and the installation secret. Because it proves this
   is the device, the server also removes **every** push subscription left on this install.

If the logout was forced (refresh failed, `subscription_suspended`, etc.), skip step 2 (the token is dead) and do
steps 3 and 4. Step 4 alone removes the subscription on the server. `401` from step 2 just means the token was
already invalid — treat as done.

## 6. Push subscription — handled by `POST /devices/`

The app registers, rotates and revokes its FCM token through `POST /devices/` (§4.2) — no separate call.
`POST /notifications/push-subscriptions/` is the **web** client's endpoint; it still accepts `installation_id`
for older app builds that call it, but new builds should not.

## 7. Server-side gate — handling `426` and `503` on any request

Independently of §3, the backend rejects requests from outdated builds and during maintenance. This can happen on
**any** endpoint except the exempt ones (below), including login/OTP/refresh. Add a Dio error handler:

```dart
onError: (e, handler) {
  final status = e.response?.statusCode;
  final data = e.response?.data;
  final code = data is Map ? data['code'] : null;
  if (status == 426 && code == 'APP_UPDATE_REQUIRED') {
    appGate.showForceUpdate(storeUrl: data['store_url'], minBuild: data['min_supported_build']);
  } else if (status == 503 && code == 'MAINTENANCE') {
    appGate.showMaintenance(message: data['message'], expiresAt: data['expires_at']);
  }
  handler.next(e);
}
```

| Status | Body | UI |
|---|---|---|
| `426` | `{"detail":"Please update the app","code":"APP_UPDATE_REQUIRED","min_supported_build":10,"store_url":"https://…"}` | non-dismissible update screen → `store_url` (may be `null` if not configured: fall back to the policy endpoint's value / a default store link) |
| `503` | `{"detail":"Down for maintenance","code":"MAINTENANCE","message":"Back at 3 PM","expires_at":"2026-10-08T15:00:00Z"}` | maintenance screen; `message` and `expires_at` may be `null`; a `Retry-After` header (seconds) is sent when `expires_at` is known |

Rules:
- **Switch on `code`, never on `detail` or the text** (the text is translated).
- A plain `5xx` (or a `503` without `code: MAINTENANCE`) is an ordinary server error — show the normal error UI,
  never the maintenance screen.
- Do not treat a `426`/`503` as an auth failure: don't log the user out, don't try to refresh the token.
- Exempt (never gated, always reachable): `GET /app/version-policy/`, everything under `/devices/`, `/admin/`.
  Login, OTP and token-refresh are **not** exempt.
- Existing codes keep working as before (`SUBSCRIPTION_SUSPENDED`, `EMAIL_NOT_VERIFIED`, …).
- Enforcement is controlled by the backend env flag `APP_VERSION_ENFORCEMENT` (`off|log|on`, default `log`). In
  `log` the server only logs "would block" — you will not see 426/503 yet, but the app must already handle them.

## 8. Suggested app flow

```
cold start
 ├─ load/generate installation_id, read PackageInfo/DeviceInfo
 ├─ GET /app/version-policy/            → force? blocking screen : maintenance? maintenance screen : soft? prompt
 ├─ POST /devices/ (signed_in = hasSession, Bearer if any, no refresh)
 └─ continue to login / home

login success      → POST /devices/ (signed_in:true, Bearer, push.fcm_token)   ← subscribes to push
FCM token refresh  → POST /devices/ (Bearer, new token)                        ← replaces the subscription
push permission    → POST /devices/ (Bearer, push.permission changed; token null if denied)
logout             → §5 sequence
resume (> check_interval_seconds) → GET /app/version-policy/
any 426/503 w/ code → blocking screen (§7)
```

## 9. Testing against a dev backend

- Make sure policy rows exist: `docker compose exec backend python manage.py seed_app_version_policies --latest-build 14`.
- In Django admin → **App version policies**, edit `min_build` / `latest_build` / maintenance fields (raising
  `min_build` asks you to tick a confirmation box). Changes apply immediately (the server cache is invalidated on save).
- To see 426/503 for real, run the backend with `APP_VERSION_ENFORCEMENT=on`.
- QA can bypass maintenance by sending `X-Maintenance-Bypass: <APP_MAINTENANCE_BYPASS_TOKEN>` (only if the server
  has that token configured).
- Quick curl:
  ```bash
  curl -s "http://localhost:8000/api/v1/app/version-policy/?platform=android&build=9&flavor=prod"
  curl -s -i http://localhost:8000/api/v1/auth/login/ -X POST \
    -H 'X-App-Platform: android' -H 'X-App-Build: 9' -H 'X-App-Flavor: prod' \
    -H 'Content-Type: application/json' -d '{"email":"a@b.co","password":"x"}'   # 426 when enforcement=on and min_build>9
  ```
- Admin → **App installations** shows what the app registered (FCM token masked) and has an **Adoption report**.

## 10. Release checklist for the app

- [ ] Headers sent on every request, including auth calls.
- [ ] `installation_id` persisted once, same in header and body.
- [ ] App-generated install secret (32 random bytes, base64url), stored in secure storage before first use, sent
      as `X-Installation-Secret` on every `POST /devices/`, never logged. `ignored: unclaimed_install` is treated
      like any `ignored`. On `403 INSTALLATION_SECRET_INVALID`: new `installation_id` + secret, then a resync that
      is queued (not awaited inside the sync loop).
- [ ] `sync_seq` persisted, increasing, serial queue, same value on retries.
- [ ] `POST /devices/` never retried on 401, never triggers a token refresh.
- [ ] Logout does §5:
  - `DELETE /devices/{id}/user/?sync_seq=<next seq>` with the access token and `X-Installation-Secret`,
    **before** clearing tokens;
  - then `deleteToken()`;
  - then the anonymous `signed_in:false` sync carrying the secret.

  A forced logout still sends that last sync.
- [ ] No call to `/notifications/push-subscriptions/` — push registration rides on `POST /devices/`.
- [ ] 426/503 handled by `code` on every request; plain 5xx is not "maintenance".
- [ ] Version-policy failure fails open.
- [ ] Build numbers strictly increase per platform/flavor in CI.
- [ ] Don't raise `min_build` on the server until the new build is fully live in the store
      (Play: staged rollout finished; App Store: released and past review — never a build still in review/TestFlight).
