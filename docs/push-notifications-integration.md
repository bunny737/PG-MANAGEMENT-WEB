# Push Notifications Integration Guide

> Companion to `docs/modules/14-notifications.md` (backend spec) and
> `docs/frontend-plan.md` §3.1a (mobile client architecture). Read those
> first for *why* things are built this way — this doc is the practical
> *how* for wiring up a client (web or Flutter).

## 1. How it works

```
                         ┌─────────────────────────┐
                         │   Firebase project        │
                         │   (Cloud Messaging)        │
                         └───────────┬────────────────┘
                                     │
                 ┌───────────────────┼───────────────────┐
                 │                   │                   │
        service-account JSON     APNs key            Web VAPID key
        (backend only)         (iOS, via Firebase)   (web only)
                 │                   │                   │
                 ▼                   ▼                   ▼
        ┌────────────────┐   ┌───────────────┐   ┌────────────────┐
        │  Django backend  │   │  Flutter app   │   │  Next.js web    │
        │  channels/push.py│   │ (iOS + Android)│   │  (Serwist SW)   │
        └────────┬─────────┘   └───────┬────────┘   └────────┬────────┘
                 │  1. client gets FCM token from Firebase SDK, then
                 │     registers it:
                 │◄───────────────────────────────────────────┘
                 │     POST /api/v1/notifications/push-subscriptions/
                 │
                 │  2. some business event happens (invoice issued,
                 │     trial reminder, ...) → apps.notifications.services
                 │     .notify() → channels/push.py sends via FCM to every
                 │     token registered for that recipient
                 ▼
        Firebase delivers the notification + data payload to the device
```

Key facts before you start:
- **One Firebase project** covers web, Android, and iOS — you register three
  "apps" inside it (Web, Android, iOS), each gets its own config, all point
  at the same underlying FCM backend.
- The backend already has the full server side built (Module 14 V2):
  `PushSubscription` model, `POST/GET/DELETE
  /api/v1/notifications/push-subscriptions/`, and `channels/push.py`
  sending via `firebase-admin`. **You do not need to write any backend
  code** — this doc is entirely about the client side plus Firebase
  console setup.
- A client only receives push for notification types the registry
  (`backend/apps/notifications/registry.py`) lists `push` as a channel for.
  Today that's `invoice_issued`, `payment_receipt`, and
  `trial_expiry_reminder`. Residents can't receive push yet — see §5.

## 2. Firebase project setup (one-time, console)

1. Go to the [Firebase console](https://console.firebase.google.com/) →
   **Add project**. Name it something like `pgmate-prod` (make a separate
   `pgmate-dev` project too — never share push credentials between
   environments).
2. Inside the project, **Project settings → Cloud Messaging** — this is
   where you'll come back for the Web VAPID key and the iOS APNs key.
3. Register three apps in **Project settings → General → Your apps**:
   - **Web app**: gives you a `firebaseConfig` object (apiKey, projectId,
     messagingSenderId, appId, ...) — used by the Next.js app.
   - **Android app**: package name must match the Flutter app's
     `applicationId` (`android/app/build.gradle`). Download
     `google-services.json`.
   - **iOS app**: bundle ID must match the Flutter app's iOS bundle
     identifier (`ios/Runner.xcodeproj`). Download
     `GoogleService-Info.plist`.
4. **Service account** (backend, server-to-FCM auth): **Project settings →
   Service accounts → Generate new private key**. This downloads a JSON
   file — this is the credential `channels/push.py` uses. Never commit it;
   never send it to a client. See §3.
5. **Web Push certificate (VAPID key)**: **Project settings → Cloud
   Messaging → Web configuration → Generate key pair**. Copy the key
   string — used by the web app in §4.
6. **APNs authentication key** (iOS): you need an Apple Developer account.
   Apple Developer portal → **Certificates, Identifiers & Profiles → Keys**
   → create a new key with the "Apple Push Notifications service (APNs)"
   capability, download the `.p8` file (you can only download it once).
   Then in Firebase: **Project settings → Cloud Messaging → Apple app
   configuration → APNs Authentication Key** → upload the `.p8` file along
   with its Key ID and your Apple Team ID.

## 3. Backend configuration (already built — reference only)

Set **one** of these in the backend's `.env` (see `.env.example`):

```bash
# Preferred in production — mount the service-account JSON as a file
FIREBASE_CREDENTIALS_PATH=/run/secrets/firebase-service-account.json

# Or, if you can't mount files (e.g. some PaaS envs) — the raw JSON as a string
FIREBASE_CREDENTIALS_JSON={"type": "service_account", ...}
```

Leave both blank in dev — the push channel just logs `status=skipped` with
a clear note (`"Push not configured (no Firebase credentials)"`), same
fail-open discipline as every other channel. Nothing else to configure
backend-side; `docker-compose.yml` already has no push-specific service —
sending happens inline inside the existing `celery`/`backend` containers.

## 4. API reference

All endpoints require the same JWT auth as the rest of the app
(`Authorization: Bearer <access_token>`, obtained from
`POST /api/v1/auth/login/`). There is no separate "push" auth.

### Register / refresh a device token
```
POST /api/v1/notifications/push-subscriptions/
Content-Type: application/json
Authorization: Bearer <access_token>

{
  "fcm_token": "<token from the Firebase SDK>",
  "device_type": "web" | "android" | "ios",
  "installation_id": "<uuid>"          // optional — Flutter app only
}
```
- `installation_id` is the app's install UUID (see
  [modules/19-app-client.md](modules/19-app-client.md)). If an install with that
  id has been registered via `POST /api/v1/devices/` the subscription is linked to
  it; an unknown id is ignored. Write-only (not echoed back).
- Returns **201** with the created row on first registration.
- Returns **200** if that exact `fcm_token` already exists (re-registering
  the same device upserts — safe to call this every time the client
  gets/refreshes a token, no need to check first).
- `device_type` must be exactly `web`, `android`, or `ios` (lowercase — this
  matches `PushSubscription.DeviceType`).

### List your own registered devices
```
GET /api/v1/notifications/push-subscriptions/
```
Returns `[{"id", "fcm_token", "device_type", "last_seen_at"}, ...]` — only
the current user's own devices (self-scoped, RLS-enforced).

### Unregister a device (call on logout / token invalidation)
```
DELETE /api/v1/notifications/push-subscriptions/{id}/
```
Returns **204**. Always call this on logout — an unregistered device
whose token is later reused by a different account would otherwise keep
receiving the previous user's pushes until FCM invalidates the stale token.

### Notification payload shape (what you'll receive)
Every push is an FCM **notification message** with a **data** payload:
```json
{
  "notification": { "title": "Invoice for July 2026", "body": "Amount due: ₹5000..." },
  "data": { "notification_type": "invoice_issued", "reference": "invoice:3f2a...-uuid" }
}
```
- `notification.title`/`.body` — because this is a "notification message"
  (not data-only), **Android and iOS auto-display it when the app is
  backgrounded or terminated** — you don't write any code for that case.
  You only need custom handling for the **foreground** case (§5, §6).
- `data.notification_type` — one of `invoice_issued`, `payment_receipt`,
  `trial_expiry_reminder` today (`registry.py`'s keys).
- `data.reference` — e.g. `invoice:<uuid>`, `payment:<uuid>`,
  `tenant_trial:<uuid>:<days>` — parse the part after `:` to know which
  record to open. This is exactly the same `reference` format already used
  in `NotificationLog.reference` server-side
  (`docs/modules/14-notifications.md` data model).

### Your own notification history & preferences
Not push-specific, but useful for a "Notifications" screen in either
client:
```
GET  /api/v1/notifications/history/                 # your own NotificationLog rows
GET  /api/v1/notifications/preferences/              # opt-in state for optional types
POST /api/v1/notifications/preferences/              # {"notification_type", "channel", "enabled"}
```

## 5. Who can actually receive push (important)

`PushSubscription.user` is an `accounts.User` — Owner, Manager, or
Receptionist. **Residents have no login account yet** (see
`apps.residents.models.Resident`'s docstring), so a Resident recipient
(the target of `invoice_issued`/`payment_receipt`) always gets `push`
logged as `skipped`, never delivered, until Module 04 adds resident login.
`trial_expiry_reminder` goes to the tenant's Owner, who *does* have a login
— that one works end-to-end today. Build your push UI/testing around Owner/
Manager/Receptionist accounts for now.

## 6. Web integration (Next.js + Serwist)

The web app already plans a Serwist service worker
(`docs/frontend-plan.md` §5.1) — this hooks Firebase's web push handling
into that same service worker rather than registering a second one.

### 6.1 Install and configure
```bash
npm install firebase
```
Add the Web app's Firebase config as env vars (`frontend/.env.local`), all
`NEXT_PUBLIC_*` since they're safe to expose to the browser (they identify
the project, they don't authenticate anything):
```bash
NEXT_PUBLIC_FIREBASE_API_KEY=...
NEXT_PUBLIC_FIREBASE_PROJECT_ID=...
NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID=...
NEXT_PUBLIC_FIREBASE_APP_ID=...
NEXT_PUBLIC_FIREBASE_VAPID_KEY=...   # from §2 step 5
```

### 6.2 Initialize Firebase + request permission + get a token
```ts
// frontend/src/lib/push.ts
import { initializeApp, getApps } from 'firebase/app';
import { getMessaging, getToken, onMessage } from 'firebase/messaging';

const firebaseConfig = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
  messagingSenderId: process.env.NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID,
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
};

export async function enablePushNotifications(accessToken: string) {
  if (typeof window === 'undefined' || !('Notification' in window)) return;

  const permission = await Notification.requestPermission();
  if (permission !== 'granted') return;

  const app = getApps().length ? getApps()[0] : initializeApp(firebaseConfig);
  const messaging = getMessaging(app);

  // Reuses the Serwist-registered service worker instead of registering a
  // second one — see 6.3 for the SW-side handler this depends on.
  const registration = await navigator.serviceWorker.ready;
  const token = await getToken(messaging, {
    vapidKey: process.env.NEXT_PUBLIC_FIREBASE_VAPID_KEY,
    serviceWorkerRegistration: registration,
  });
  if (!token) return;

  await fetch('/api/v1/notifications/push-subscriptions/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${accessToken}` },
    body: JSON.stringify({ fcm_token: token, device_type: 'web' }),
  });

  // Foreground messages don't auto-display — build your own UI toast/banner.
  onMessage(messaging, (payload) => {
    console.log('Push received in foreground:', payload);
    // e.g. show a toast, and use payload.data.reference to deep-link on click.
  });
}
```
Call `enablePushNotifications()` from wherever the app already knows the
logged-in user and their access token (e.g. right after login, or from a
"Enable notifications" button/settings toggle — don't call it unprompted on
every page load, browsers throttle/distrust apps that spam the permission
prompt).

### 6.3 Background handling in the service worker
Add Firebase's background handler into the existing Serwist `sw.ts`
(`docs/frontend-plan.md` §5.1) rather than a separate
`firebase-messaging-sw.js` — Firebase's web SDK supports this via the
compat build inside any service worker:
```ts
// frontend/src/sw.ts (add alongside the existing Serwist setup)
import { initializeApp } from 'firebase/app';
import { getMessaging, onBackgroundMessage } from 'firebase/messaging/sw';

const firebaseApp = initializeApp({
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
  messagingSenderId: process.env.NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID,
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
});
const messaging = getMessaging(firebaseApp);

// Only fires when the tab isn't focused — the browser already auto-displays
// the notification.title/body; this is where you'd add a click handler.
onBackgroundMessage(messaging, (payload) => {
  console.log('Background push:', payload);
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const reference = event.notification.data?.FCM_MSG?.data?.reference;
  // e.g. parse reference ("invoice:<uuid>") and open the matching page.
  event.waitUntil(self.clients.openWindow('/'));
});
```

### 6.4 Unregister on logout
```ts
await fetch(`/api/v1/notifications/push-subscriptions/${subscriptionId}/`, {
  method: 'DELETE',
  headers: { Authorization: `Bearer ${accessToken}` },
});
```
Keep the subscription `id` (from the POST response) somewhere retrievable
at logout — e.g. alongside the session, or just `GET` the list and match by
the current device's token.

## 7. Flutter integration (Android + iOS)

### 7.1 Install packages
```bash
flutter pub add firebase_core firebase_messaging flutter_local_notifications
```
`flutter_local_notifications` is needed because **FCM notification
messages do not auto-display while the app is in the foreground**, on
either platform — without it, a push that arrives while the user has the
app open produces no visible UI at all.

### 7.2 Connect the Flutter app to the Firebase project
Use the [FlutterFire CLI](https://firebase.google.com/docs/flutter/setup) —
it wires up both platforms in one step instead of manually placing config
files:
```bash
dart pub global activate flutterfire_cli
flutterfire configure --project=pgmate-prod
```
This generates `lib/firebase_options.dart` and places
`android/app/google-services.json` and `ios/Runner/GoogleService-Info.plist`
automatically (pulled from the Firebase project you registered in §2 —
select the same Web/Android/iOS app entries). Run this once per environment
(`pgmate-dev`, `pgmate-prod`) and keep the generated files out of git if
they contain anything env-specific — check what FlutterFire generates
against your existing secret-handling convention.

### 7.3 Android-specific setup
- `android/app/build.gradle`: `minSdkVersion` must be **21+** (FCM
  requirement) — Jetpack Compose isn't in play anymore, but confirm this
  against whatever Flutter's default template sets.
- No extra permission needed for Android 12 and below. **Android 13+**
  requires the runtime notification permission — request it explicitly
  (see §7.5, `requestPermission()` covers this on Flutter's plugin, but
  Android additionally needs the `POST_NOTIFICATIONS` manifest permission,
  which `firebase_messaging`'s Android setup docs cover).

### 7.4 iOS-specific setup
- Requires a **paid Apple Developer account** (push entitlements aren't
  available on the free tier).
- In Xcode: enable the **Push Notifications** capability and **Background
  Modes → Remote notifications** on the `Runner` target.
- The APNs key uploaded to Firebase in §2 step 6 is what lets
  `firebase_messaging` bridge APNs ↔ FCM — no separate APNs code needed in
  Dart.
- iOS requires an explicit permission prompt (handled by
  `FirebaseMessaging.instance.requestPermission()`, §7.5) — unlike Android,
  a denied prompt cannot be re-requested by the app; the user must change it
  in iOS Settings.

### 7.5 Initialize, request permission, get the token
```dart
// lib/push_notifications.dart
import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'firebase_options.dart';
import 'api_client.dart'; // your existing dio/http client with the JWT

final _localNotifications = FlutterLocalNotificationsPlugin();

// Must be a top-level function — background messages run in a separate
// isolate with no access to app state.
@pragma('vm:entry-point')
Future<void> firebaseMessagingBackgroundHandler(RemoteMessage message) async {
  await Firebase.initializeApp(options: DefaultFirebaseOptions.currentPlatform);
  // Notification messages auto-display in background on both platforms —
  // usually nothing to do here beyond optional analytics/logging.
}

Future<void> initPushNotifications(ApiClient api) async {
  await Firebase.initializeApp(options: DefaultFirebaseOptions.currentPlatform);
  FirebaseMessaging.onBackgroundMessage(firebaseMessagingBackgroundHandler);

  final messaging = FirebaseMessaging.instance;
  final settings = await messaging.requestPermission(alert: true, badge: true, sound: true);
  if (settings.authorizationStatus == AuthorizationStatus.denied) return;

  await _localNotifications.initialize(
    const InitializationSettings(
      android: AndroidInitializationSettings('@mipmap/ic_launcher'),
      iOS: DarwinInitializationSettings(),
    ),
    onDidReceiveNotificationResponse: (response) {
      // response.payload carries the "reference" you attach below — use it
      // to deep-link (e.g. navigatorKey.currentState?.pushNamed(...)).
    },
  );

  final token = await messaging.getToken();
  if (token != null) await _registerToken(api, token);

  // FCM tokens can change (app reinstall, Firebase-internal rotation) —
  // re-register whenever this fires, not just once at startup.
  messaging.onTokenRefresh.listen((newToken) => _registerToken(api, newToken));

  // Foreground: build the visible notification yourself.
  FirebaseMessaging.onMessage.listen((message) {
    final notification = message.notification;
    if (notification == null) return;
    _localNotifications.show(
      notification.hashCode,
      notification.title,
      notification.body,
      const NotificationDetails(
        android: AndroidNotificationDetails('default_channel', 'General'),
        iOS: DarwinNotificationDetails(),
      ),
      payload: message.data['reference'],
    );
  });

  // User tapped a notification while the app was backgrounded (not
  // terminated) — this is where you deep-link.
  FirebaseMessaging.onMessageOpenedApp.listen((message) {
    final reference = message.data['reference']; // e.g. "invoice:<uuid>"
    // navigate based on message.data['notification_type'] + reference
  });

  // App was fully terminated and opened via a notification tap.
  final initialMessage = await messaging.getInitialMessage();
  if (initialMessage != null) {
    final reference = initialMessage.data['reference'];
    // same deep-link handling as onMessageOpenedApp
  }
}

Future<void> _registerToken(ApiClient api, String token) async {
  await api.post('/api/v1/notifications/push-subscriptions/', data: {
    'fcm_token': token,
    'device_type': defaultTargetPlatform == TargetPlatform.iOS ? 'ios' : 'android',
  });
}
```
Call `initPushNotifications(api)` once the user is logged in and you have
an authenticated `ApiClient` (same JWT the rest of the app uses — see
`docs/frontend-plan.md` §3.1a for the login/token-refresh/secure-storage
pattern this should reuse, not duplicate).

### 7.6 Unregister on logout
```dart
await api.delete('/api/v1/notifications/push-subscriptions/$subscriptionId/');
```
Keep the subscription `id` from the registration response (or `GET` the
list and match by the device's current token) so logout can clean it up —
same reasoning as the web client in §6.4.

## 8. Testing checklist

- [ ] Register a device (web and/or Flutter), confirm it appears via
      `GET /api/v1/notifications/push-subscriptions/`.
- [ ] Trigger `trial_expiry_reminder` in a dev environment (it's the one
      type that reaches a real `User` today — see §5) and confirm the push
      arrives:
      - App backgrounded/terminated → OS auto-displays it.
      - App foregrounded → your `onMessage`/`onBackgroundMessage` handler
        fires and you show something.
- [ ] Tap the notification → confirm `data.reference` reaches your
      deep-link handler (`onMessageOpenedApp` / `getInitialMessage` on
      Flutter, `notificationclick` on web).
- [ ] Force an `UnregisteredError` (uninstall the app / clear site data,
      then trigger another push) and confirm — via Django admin on
      `NotificationLog` — the second attempt logs `skipped` with `'All
      registered devices were unregistered.'` and the stale
      `PushSubscription` row is gone.
- [ ] Log out → confirm the `DELETE` call fires and the row disappears from
      `GET /api/v1/notifications/push-subscriptions/`.
- [ ] Disable push for `invoice_issued` via
      `POST /api/v1/notifications/preferences/
      {"notification_type": "invoice_issued", "channel": "push", "enabled": false}`
      and confirm no push log entry is created for that channel on the next
      invoice issue (email should still fire).

## 9. Troubleshooting

| Symptom | Likely cause |
|---|---|
| `POST /push-subscriptions/` returns 401 | Access token missing/expired — same auth as every other endpoint, not push-specific. |
| Push never arrives, `NotificationLog` shows `skipped: "Push not configured (no Firebase credentials)"` | Backend `.env` has neither `FIREBASE_CREDENTIALS_PATH` nor `FIREBASE_CREDENTIALS_JSON` set. |
| `skipped: "Recipient has no linked login account..."` | The recipient is a `Resident`, not a `User` — expected today, see §5. |
| `skipped: "No registered push devices for this user."` | The client never called (or the call failed) `POST /push-subscriptions/` for that account. |
| Web: no push in foreground, but background works | Expected — `onMessage` (foreground) and the SW's `onBackgroundMessage` are separate handlers; you must implement both (§6.2, §6.3). |
| Flutter: notification arrives but tapping it does nothing | Check `data.reference` is actually read in `onMessageOpenedApp`/`getInitialMessage` (backgrounded/terminated) vs. your `flutter_local_notifications` `payload` callback (foreground) — these are three different code paths for the same "user tapped it" outcome. |
| iOS: never receives anything, no error | Almost always the APNs key (§2 step 6) — confirm it's uploaded in Firebase console under the correct Team ID/Key ID, and that the Push Notifications capability is enabled in Xcode. |
| `firebase_admin` `UnregisteredError` in Django logs on every send | Expected/handled — `channels/push.py` catches this and prunes the stale token automatically; not a bug. |
