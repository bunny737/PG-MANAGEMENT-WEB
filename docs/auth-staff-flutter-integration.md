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
4. When the logged-in user lacks Finance / Tenants access (a **Receptionist** by default, or any
   staff member whose modules the Owner reduced), several JSON **keys are completely absent**
   from Resident/Bed responses (not `null` — *absent*) and `current_occupant` can be `null`.
   A non-nullable Dart model will crash. See §4. This is the single most likely thing to break
   if model classes were only tested as Owner.
5. Drive all UI (nav, buttons, screens, redirects) off the `permissions` array from
   `/auth/me/`, never off `role == "manager"` string checks — an Owner can now tune each staff
   member's access **per person** (§5), so the role no longer tells you what someone can do.
   This mirrors the web app's `PermissionGate`/`RequirePermission` pattern
   (`frontend/src/components/shared/`).

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

### 1.5 Optional email code login (added 2026-10-21)
An alternative to the password, offered on the web as "Email me a code instead" in both the Owner
and Staff views. Works for any tenant user with an email (Owners, and staff who have one; never
Super Admins).

```
POST /api/v1/auth/otp/email/request/   {"email": "..."}
  → 200 {"detail": "..."}  for every address (never reveals whether it is registered)
  → 429 when throttled (3/min per IP, 5/hour per email)
POST /api/v1/auth/otp/email/verify/    {"email": "...", "code": "123456"}
  → 200 {"access": "...", "refresh": "..."}   (same claims as password login)
  → 400 when `code` is not exactly 6 digits (no attempt used)
  → 401 INVALID_OTP (wrong, expired, used, or 5 wrong attempts) · 401 SUBSCRIPTION_SUSPENDED
```
The code expires in 5 minutes. A new request replaces the previous email code (a phone code is
unaffected), so only the most recent email works. A successful verify also marks the email verified.
Apply the same role check the screen applies to password login.

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

## 4. Missing keys — absent, not `null`

What a user sees depends on their **module access** (§5), not just their role. These fields are
**removed from the JSON entirely** (not sent as `null`):

| Field(s) | Present only if the user has |
|---|---|
| Resident: `contracted_rent`, `billing_mode` | `view_finance` |
| Resident: `security_deposit_amount`, `advance_amount`, `advance_refundable` | `view_finance` **or** `manage_deposits` |
| Bed: `history` | `view_activity_timeline` **and** `view_resident_profile` |
| Bed: `current_occupant.rent` | `view_finance` |
| Bed: `current_occupant` itself | `view_resident_profile` — otherwise the key is present but **`null`** |

Defaults: Owner/Manager have everything; a **Receptionist** has none of the finance fields, no
`history`, but does see `current_occupant` (name/phone, no rent).

**This is a key-presence difference, not a `null` value** (except `current_occupant`, which is
`null`). If your Dart model uses `json_serializable`/`freezed` with these fields
required/non-nullable, deserializing throws. Make every field above optional in the model
(`String? contractedRent`, …) regardless of which role you test with — a model only tested as
Owner/Manager passes CI and breaks the first time a Receptionist, or a Manager whose Finance
module was turned off, opens that screen. Likewise hide the rent/finance UI instead of rendering a
zero. Same as `frontend/src/features/properties/BedDetails.tsx` and
`frontend/src/features/residents/ResidentProfile.tsx`, which tolerate absent fields.

## 5. Drive UI off `permissions`; access is per person

`/auth/me/`'s `permissions` array (§3) is the *only* thing that should gate what a screen or
button does. **Since 2026-10-12 it is per person**: the role gives the defaults, and the Owner can
override each Manager's/Receptionist's access per *module* (Dashboard, Properties, Tenants,
Finance, Reports, Complaints, Visitors) with a level (**off / view / full**, only where a module
supports it) from the Team Management screen (§6.1). Never hardcode "if role == manager, show X".
Mirror the web app's pattern:
- `PermissionGate` (`frontend/src/components/shared/PermissionGate.tsx`) — renders nothing if the
  permission is missing. Flutter equivalent: a widget taking a permission string and returning its
  child or `SizedBox.shrink()`.
- `RequirePermission` — gates an entire route. If the permission is missing, send the user to the
  **first screen their permissions allow** (`firstAllowedRoute` in `frontend/src/lib/permissions.ts`),
  else their profile — never a hardcoded role landing page. Do the same after login.

Permission codes you will see for the module screens: `view_dashboard` (dashboard screen),
`view_property_features` (properties), `view_resident_profile` (tenants), `view_finance`
(finance reads), `view_reports`, `manage_complaints`, `manage_visitors`; write actions use the
`manage_*` codes (`manage_invoices`, `manage_payments`, `manage_residents`, …).

**Keeping the cache fresh.** The API enforces a change **immediately** (a revoked permission 403s
on the very next request), but the app's cached `permissions` only update when `/auth/me/` is
re-fetched. Re-fetch on app resume (throttle ~60 s) and **immediately after any `403` with
`code: "PERMISSION_DENIED"`** (bypass the throttle), then re-evaluate the gates; otherwise a user
whose access was just reduced keeps seeing screens that now fail.

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

### 6.1 Module access (reference only, no mobile UI yet)
`manage_staff_accounts` (Owner/Super Admin) only; the target must be a Manager/Receptionist of the
caller's tenant (anything else is `404`).
```
GET    /api/v1/staff/{id}/module-access/   → { role, customized, modules: [ { key, levels, level, default_level } ] }
PUT    /api/v1/staff/{id}/module-access/   { "role": "manager", "levels": { "dashboard": "full", "finance": "view", ... } }
DELETE /api/v1/staff/{id}/module-access/   reset to role defaults (same response shape as GET)
```
- Render from the server's registry: `modules[].key` + `levels` (each module lists only the levels it
  supports, lowest first, always starting with `off`). A module with a single non-off level is a
  plain toggle; Properties, Tenants and Finance also get a level picker. Names/labels are your i18n
  (keyed by `key` and level) — don't hardcode the module list.
- **`PUT` is a complete replacement**: send every module key. Unknown module or an unsupported
  level → `400` with per-module errors under `levels`. `role` is the role your screen rendered; if
  it changed meanwhile the server answers `409 { "code": "ROLE_CHANGED" }` — refetch and show a notice.
- Levels equal to the role defaults are stored as "not customized" (`customized: false`).
- Changing a staff member's role (`PATCH /staff/{id}/`) resets their access to the new role's defaults.
- Autosave pattern used on web (`frontend/src/features/staff/useModuleAccess.ts`): apply optimistically,
  one serialized worker sends the latest complete map, roll back to the last server-confirmed state on
  failure.
- **Registry growth**: a module added in a later release resolves to `off` for staff who already have a
  saved override (they don't inherit the role default) — expect new modules to appear switched off.

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
- [ ] Log in as a Receptionist, and as a Manager whose Finance/Tenants modules the Owner turned
      off, open screens that render `Resident`/`Bed` data, and confirm nothing crashes on the missing
      `contracted_rent`/`billing_mode`/deposit-figure/`history`/`current_occupant.rent` keys or a
      `null` `current_occupant` (§4).
- [ ] Confirm nav/buttons for Owner-only actions (staff management, property assignment) are
      absent for a Manager/Receptionist session, driven by the `permissions` array, not a role
      check — and that reducing a module from the Owner's session removes its screens for that
      staff user after the next `/auth/me/` refresh (resume or after a `403`).
- [ ] Account deletion (§10): request it as an Owner and as a Manager, confirm the next call on a stale token gets
      `PASSWORD_CHANGED`, the returned token pair works for `GET /auth/me/`, any other route answers `403` with
      `ACCOUNT_DELETION_PENDING` / `TENANT_DELETION_PENDING`, and cancelling restores access.
- [ ] Try phone formats `9876543210`, `09876543210`, `+91 98765 43210`, `919876543210` against
      `login-phone/` with the same account — all four should succeed (same canonical number).
      Try an 11-digit number not starting with `0`, or a 10-digit number not starting 6–9 — both
      should be rejected, not silently truncated into something that happens to work.

## 9. Troubleshooting

| Symptom | Likely cause |
|---|---|
| `login-phone/` always returns `INVALID_CREDENTIALS` even with the right password | Check the phone format you're sending actually normalizes to the stored 10-digit value (§1.2) — a format outside the three accepted shapes is rejected outright, not fuzzy-matched. |
| A session gets logged out right after you reset *a different* staff member's password | Shouldn't happen — `auth_version` is per-user. If it does, that's a real bug, not expected behavior; file it rather than working around it. |
| Resident/Bed JSON deserialization crashes only for one test account | Almost always a Receptionist (or a staff user with Finance/Tenants reduced) hitting §4 — check which fields are missing in the raw response vs. what your model requires. |
| `/auth/me/.email` is `null` and some unrelated feature breaks | That feature assumed every account has an email — see §3, fix the assumption, not the test data. |
| Staff creation returns 400 with no top-level `code` you recognize | Expected for ordinary validation errors (§6) — read the field-keyed message array instead of switching on `code`. |

## 10. Account deletion (Google Play requirement — the app MUST expose it)

Play requires an **in-app** way to delete the account (the public page `/delete-account` is the web half).
Minimum: Settings → **Delete account** that opens that page in the browser. Better: a native screen using the
API below. Backend spec: [modules/22-account-deletion.md](modules/22-account-deletion.md).

| Call | Purpose |
|---|---|
| `GET /api/v1/auth/me/` | `deletion` is `null` or `{scope: user\|tenant, status: pending\|processing\|failed, scheduled_for, can_cancel}`; `deletion_confirm_methods` lists what can confirm a request (`password`, `otp_email`; offer only these) |
| `POST /api/v1/auth/account/deletion/otp/` | emails a 6-digit **deletion** code (a login code will not work here) |
| `POST /api/v1/auth/account/deletion/` | body `{password}` **or** `{otp}`, `confirm: true`, optional `reason` → `201 {deletion, access, refresh}` |
| `GET /api/v1/auth/account/deletion/` | the active request; `404` when none |
| `DELETE /api/v1/auth/account/deletion/` | cancel (`204`); `409` unless still `pending`; `403` for staff on their Owner's request |

Behaviour to implement:
- **Owner = the whole business.** Say so, and point at the exports first. Manager/Receptionist delete only themselves.
- A successful request **ends every session** (like a password change). Store the returned pair immediately; the
  old tokens get `PASSWORD_CHANGED` (§2). For an Owner this also signs out all staff.
- While a request is active **everything except** `GET /auth/me/` and the deletion endpoint answers
  **`403`** with `code` `ACCOUNT_DELETION_PENDING` (the requester) or `TENANT_DELETION_PENDING` (staff of that
  business). This is **not** a dead session — do not log out or refresh-loop. Route to a "scheduled for deletion"
  screen showing `scheduled_for` (IST) and, if `can_cancel`, a Cancel button. Login and refresh still work so the
  user can get back to that screen even if the business was suspended meanwhile.
- `processing` can no longer be cancelled; `failed` means the deletion is delayed and support has been notified —
  show it, keep the account locked, no cancel.
- A phone-only user with no usable password and no email cannot confirm online (`deletion_confirm_methods` is
  empty): send them to support (`GET /api/v1/support/`).
- The app-client gate (force-update / maintenance) still applies to these routes; the web page is the fallback.
