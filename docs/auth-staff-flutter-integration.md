# Flutter integration guide — phone+password login, staff management, token revocation

> Companion to [modules/01-auth-tenancy.md](modules/01-auth-tenancy.md) and
> [modules/02-property-hierarchy.md](modules/02-property-hierarchy.md) (backend specs, the source of
> truth) and `docs/frontend-plan.md` §3.1a (mobile client architecture: same Django API, no proxy,
> `flutter_secure_storage` for tokens). This doc is the practical *how* for what changed on this
> branch. All paths are under `{BASE_URL}/api/v1/`. Nothing here needs a new backend endpoint if
> you're only building login + "logged-in user sees their own role's screens" — read §0 and §1
> first, skip the rest until you actually build an Owner-side staff-management screen on mobile.

## 0. TL;DR — what the app must do

1. Two login endpoints now exist. Pick based on what the account was given — see §1.
2. Every authenticated request can now fail with `code: "PASSWORD_CHANGED"` even on a token that
   hasn't expired yet. Handle it distinctly from a normal 401 — see §2.
3. `email` can be `null` on `/auth/me/` and in any staff list. Don't assume every account has one —
   see §3.
4. If the logged-in user is a **Receptionist**, several JSON **keys are completely absent** from
   Resident/Bed responses (not `null` — *absent*). A non-nullable Dart model will crash. See §4.
   This is the single most likely thing to break if copy-pasted model classes from Owner/Manager
   testing.
5. Drive all UI (nav, buttons, screens) off the `permissions` array from `/auth/me/`, never off
   `role == "manager"` string checks — see §5. This mirrors the web app's `PermissionGate`/
   `RequirePermission` pattern (`frontend/src/components/shared/`).

## 1. Login: two endpoints

Owners have always had email (required, unchanged). Manager/Receptionist accounts now often have
**no email at all** — the Owner creates them with just a phone number and a password set directly
(there's no SMS/OTP delivery yet, see Module 01 Decisions), so they can't use email+password login.

### 1.1 Email + password (unchanged)
```
POST /api/v1/auth/login/
{ "email": "owner@example.com", "password": "..." }
→ 200 { "access": "...", "refresh": "..." }
```
Fails with `EMAIL_NOT_VERIFIED` if the account has an email that hasn't been verified yet — this
gate **only** applies to this endpoint (see §1.3).

### 1.2 Phone + password (new)
```
POST /api/v1/auth/login-phone/
{ "phone": "9876543210", "password": "..." }
→ 200 { "access": "...", "refresh": "..." }
```
- `phone` must normalize to a plain 10-digit Indian mobile number. The backend accepts (after
  stripping all non-digit characters): exactly 10 digits; 11 digits starting with `0`; 12 digits
  starting with `91`. Anything else is rejected — **do not** send `+91-98765-43210` style
  punctuation as-is; strip it client-side to digits before sending (or just send raw digits, the
  backend strips punctuation itself — but it will *reject* a shape outside the three above, it
  won't try to guess).
- On any failure (unknown phone, wrong password, inactive account) the response is **always** the
  same generic `401 { "detail": "Invalid credentials.", "code": "INVALID_CREDENTIALS" }` — don't
  try to distinguish "no such phone" from "wrong password" in the UI; the backend deliberately
  doesn't tell you which.
- No `EMAIL_NOT_VERIFIED` gate here, even if the account also has an unverified email — phone
  ownership isn't related to email ownership.

### 1.3 Which one to call
There's no single "detect the identifier" trick worth building — just offer both as separate tabs
(same UX as the web login screen, `frontend/src/features/auth/LoginForm.tsx`): an email+password
tab and a phone+password tab. An account always has *at least one* of email/phone (enforced at the
DB level), so one of the two tabs will always work for any given user.

### 1.4 OTP login still exists but isn't production-usable yet
`POST /api/v1/auth/otp/request/` + `POST /api/v1/auth/otp/verify/` still exist and also skip the
email-verified gate, but the OTP delivery is still a backend stub that only logs the code
server-side (no SMS provider wired up — PRD V2). **Don't build OTP UI yet** — phone+password (§1.2)
is the intended path until SMS exists.

## 2. Token revocation: `PASSWORD_CHANGED`

Every account now carries a server-side `auth_version` counter, stamped into both the access and
refresh token at login. **Any** password change — a self-service reset, or an Owner resetting a
staff member's password — increments it immediately. On the very next request with an
older-than-current token:

```
401 { "detail": "Password has been changed. Please log in again.", "code": "PASSWORD_CHANGED" }
```

This fires on **any** authenticated endpoint, not just login/refresh, and on the refresh endpoint
too (so refreshing with a stale refresh token doesn't silently mint a fresh access token that's
also stale). Handle it distinctly from a normal `401` (expired access token → try refresh) and from
`SUBSCRIPTION_SUSPENDED` (tenant suspended → different message): show "your password was changed —
please log in again" and force a clean logout, **don't** attempt a token refresh when you see this
code — the refresh token is equally invalid.

```dart
onError: (e, handler) {
  final code = (e.response?.data is Map) ? e.response?.data['code'] : null;
  if (code == 'PASSWORD_CHANGED') {
    authGate.forceLogout(reason: 'password_changed'); // show the message, clear tokens, go to login
    return handler.next(e);
  }
  // ... existing SUBSCRIPTION_SUSPENDED / 426 / 503 handling (see app-client-flutter-integration.md §7)
  handler.next(e);
}
```

**One-time deploy note, not a bug you'll hit repeatedly**: rolling out this change invalidated every
token that existed before the deploy (they carry no `auth_version` claim at all, which never equals
the current value). If you're testing against a long-running dev backend from before this branch
merged, just log in again once.

## 3. `email` is now optional — `/auth/me/` and staff responses

`GET /api/v1/auth/me/` (and every `StaffUser` row from `/api/v1/staff/`) can have `"email": null`.
This was always a possible shape in the API contract but is now common in practice (phone-only
staff). Checklist:
- Dart model fields for `email` must be `String?`, never `String`.
- Don't use email as a display fallback / avatar-seed / anything-required — use `first_name` +
  `last_name`, which are always present.
- `phone` is **not** optional for Manager/Receptionist (DB-enforced), but **is** optional for
  Owner/Super Admin (rare in practice, but don't assume non-null there either).

`/auth/me/` response shape (unchanged otherwise):
```json
{
  "id": "...", "email": null, "first_name": "Ramesh", "last_name": "Kumar",
  "phone": "9876543210", "role": "manager", "language_code": "en",
  "email_verified": false, "tenant": { "id": "...", "name": "...", "status": "active", ... },
  "permissions": ["manage_property_settings", "manage_rooms_beds", "..."]
}
```

## 4. Receptionist data minimization — keys are *absent*, not `null`

If the logged-in user's role is `receptionist` (lacks the `manage_residents` permission), the
backend **removes these keys entirely** from every `Resident` object:
`contracted_rent`, `billing_mode`, `security_deposit_amount`, `advance_amount`,
`advance_refundable`.

And from every `Bed` object: the `history` key is removed entirely (if the role lacks
`view_activity_timeline` — true for both Manager and Receptionist), and inside `current_occupant`
(when present), the nested `rent` key is removed (if the role lacks `manage_residents` — true for
Receptionist only).

**This is a key-presence difference, not a `null` value.** If your Dart model uses
`json_serializable`/`freezed` with these fields marked required/non-nullable, deserializing a
Receptionist's response for Resident/Bed data **throws**, not "shows null." Make every one of these
fields optional in the model (`String? contractedRent`, etc.) regardless of which role you're
testing with — a model that only gets tested as Owner/Manager will pass CI and break in production
the first time a Receptionist account opens that screen.

Same principle as `frontend/src/features/properties/BedDetails.tsx` already handles on web (built
in the same commit, `060fdad`) — it tolerates missing `rent`/`history` rather than assuming
presence.

## 5. Drive UI off `permissions`, never off role strings

`/auth/me/`'s `permissions` array (§3) is the *only* thing that should gate what a screen/button
does. The backend's permission matrix (`backend/apps/core/roles.py`) decides what each role can do
— it is **not owner-configurable** (there's no "pick individual permissions" UI anywhere, web or
otherwise; an Owner only ever picks a role, and the role's fixed permission set follows). Mirror the
web app's pattern:
- `PermissionGate` (`frontend/src/components/shared/PermissionGate.tsx`) — renders nothing if the
  permission is missing. Flutter equivalent: a widget that takes a permission string and either
  returns its child or `SizedBox.shrink()`.
- `RequirePermission` (`frontend/src/components/shared/RequirePermission.tsx`) — gates an entire
  route/page. Flutter equivalent: a route guard checked against the cached `permissions` list
  before pushing the page.

Cache the `permissions` list once after login (and refresh it if you ever re-fetch `/auth/me/`,
e.g. after a role change — see §6). Never hardcode "if role == manager, show X" — the permission
codes are the contract, not the role names (a future role or a matrix change shouldn't require an
app update to respect it correctly, since the client already just checks the list).

## 6. Staff management endpoints (only if/when an Owner-side mobile screen is built)

These exist and are tested, but **no mobile UI for them exists yet** — this section is reference
for whenever that screen gets built, not something to wire up as part of basic login support.

```
GET    /api/v1/staff/                     list (tenant-scoped, Manager/Receptionist only)
POST   /api/v1/staff/                     create — see shape below
PATCH  /api/v1/staff/{id}/                update first_name/last_name/phone/role/is_active
POST   /api/v1/staff/{id}/set-password/   { "password": "..." } → resets immediately, revokes
                                           that staff member's existing sessions (§2)
```
All four require the `manage_staff_accounts` permission (Owner/Super Admin only — check
`permissions`, don't assume by role name, per §5).

**Create** (`POST /api/v1/staff/`):
```json
{ "first_name": "Ramesh", "last_name": "Kumar", "phone": "9876543210",
  "email": null, "role": "manager", "password": "SomeStrongPassword123" }
```
- `phone` is **required** regardless of email (unconditional for Manager/Receptionist).
- Provide `password` **or** `email` (or both) — at least one, so there's some way the account can
  actually be accessed. If you provide a password and no password-strength issue, the account is
  usable immediately with no invite step. If you provide an email and no password, an invite email
  is sent with a set-password link instead — this will never deliver to a phone-only staff member,
  so **always send `password` on mobile create flows**.
- If you provide both `email` and `password`, a verification-only email is still sent (so that
  staff member can *later* also use email+password login once they click it) — not an error, just
  background behavior you don't need to react to.

**Error shapes to expect** — this backend deliberately does **not** send a reliable per-field
machine code for ordinary validation errors; only a handful of cross-cutting situations get a
top-level `code` you can safely switch on:
```
EMAIL_NOT_VERIFIED, SUBSCRIPTION_SUSPENDED, PASSWORD_CHANGED, INVALID_CREDENTIALS,
NO_ACTIVE_ACCOUNT, EMAIL_TAKEN, PHONE_TAKEN, PHONE_REQUIRED, IDENTIFIER_REQUIRED
```
`EMAIL_TAKEN`/`PHONE_TAKEN` arrive with **409** and always come with a top-level `code` (these are
the rare database-level race-condition path — two people creating the same phone number at once).
The **normal**, far more common case — a straightforward "that phone is already active" caught
during validation — is a plain **400** with just `{"phone": ["An account with this phone number
already exists."]}` and **no useful top-level code** (DRF's default is a generic `"INVALID"`,
ignore it). **Parse the field-keyed message array** (`email`/`phone`/`password`), the same way the
web client does (`frontend/src/lib/api.ts` → `ApiError.fieldError()`, used in
`frontend/src/features/staff/StaffDirectory.tsx`) — don't try to build a clean `switch` on error
codes for staff-creation validation, only for the short list above.

## 7. Property-staff assignment endpoints (reference only, no mobile UI yet)

A Manager/Receptionist only sees properties explicitly assigned here; an Owner implicitly sees
every property and is never assigned. Requires the `assign_staff_to_properties` permission
(Owner/Super Admin).

```
GET    /api/v1/staff-property-assignments/?staff={id}      list assignments (filter by staff or property)
POST   /api/v1/staff-property-assignments/                 { "staff": "<user-id>", "property": "<property-id>" }
DELETE /api/v1/staff-property-assignments/{assignment_id}/  revoke access (204)
```
`POST` response includes `staff_name`/`property_name` read-only conveniences alongside the ids. A
duplicate assignment (same staff+property twice) is a `400` via the model's own unique constraint —
check first with the `GET ...?staff={id}` list if you're building a toggle UI (same approach as
`frontend/src/features/staff/StaffDirectory.tsx`'s "Manage Property Access" modal).

## 8. Testing checklist

- [ ] Create a staff account with phone + password only, no email — confirm
      `POST /api/v1/auth/login-phone/` succeeds immediately (no invite step needed).
- [ ] Same account: confirm `POST /api/v1/auth/login/` (email+password) is simply not usable
      (no email was ever set) rather than erroring in a confusing way — there's nothing to log in
      with.
- [ ] Log in, reset that account's password via `set-password/` from a second "Owner" session,
      confirm the first session's next request gets `PASSWORD_CHANGED` and your app shows a clean
      "log in again" flow rather than looping on refresh.
- [ ] Log in as a Receptionist, open a screen that renders `Resident`/`Bed` data, confirm it
      doesn't crash on the missing `contracted_rent`/`billing_mode`/`security_deposit_amount`/
      `advance_amount`/`advance_refundable`/`history`/`current_occupant.rent` keys (§4).
- [ ] Confirm nav/buttons for Owner-only actions (staff management, property assignment) are
      absent for a Manager/Receptionist session, driven by the `permissions` array, not a role
      check.
- [ ] Try phone formats `9876543210`, `09876543210`, `+91 98765 43210`, `919876543210` against
      `login-phone/` with the same account — all four should succeed (same canonical number).
      Try an 11-digit number not starting with `0`, or a 10-digit number not starting 6–9 — both
      should be rejected, not silently truncated into something that happens to work.

## 9. Troubleshooting

| Symptom | Likely cause |
|---|---|
| `login-phone/` always returns `INVALID_CREDENTIALS` even with the right password | Check the phone format you're sending actually normalizes to the stored 10-digit value (§1.2) — a format outside the three accepted shapes is rejected outright, not fuzzy-matched. |
| A session gets logged out right after you reset *a different* staff member's password | Shouldn't happen — `auth_version` is per-user. If it does, that's a real bug, not expected behavior; file it rather than working around it. |
| Resident/Bed JSON deserialization crashes only for one test account | Almost always a Receptionist account hitting §4 — check which fields are missing in the raw response vs. what your model requires. |
| `/auth/me/.email` is `null` and some unrelated feature breaks | That feature assumed every account has an email — see §3, fix the assumption, not the test data. |
| Staff creation returns 400 with no top-level `code` you recognize | Expected for ordinary validation errors (§6) — read the field-keyed message array instead of switching on `code`. |
