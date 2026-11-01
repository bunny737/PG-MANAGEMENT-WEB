# Flutter integration guide — resident accounts and linking to a PG

> Companion to [modules/26-resident-identity.md](modules/26-resident-identity.md) (backend spec, the source of
> truth), [app-client-flutter-integration.md](app-client-flutter-integration.md) (the `X-App-*` headers, version
> policy and device registration every request needs) and [auth-staff-flutter-integration.md](auth-staff-flutter-integration.md).
> All paths are under `{BASE_URL}/api/v1/`. This covers **Module 26a**; the `/me/*` data endpoints (bills, notices,
> complaints, visitors) arrive with 26b.

## 0. The model in one minute

- A **resident record** belongs to the PG. It needs no login, and billing works without the app.
- An **app account** is the person's own login. **They create it; staff never do.** One account can be linked to
  several PGs, and may share an email with a staff account (different pool).
- A **link** ("residency") connects the account to a PG's record. It is created only by (a) the person **accepting a
  staff invite**, or (b) staff **approving a link request** the person made with the PG's **join code**.
- A new account has **no residencies**. That is a normal state: show "Link my PG", not an error.

The access tokens are the same JWT pair as everywhere else. A resident token has `role: "resident"` and
`tenant_id: null`.

## 1. Creating the account

All of these are anonymous and throttled; none reveals whether an email has an account.

| Step | Call | Notes |
|---|---|---|
| Sign up | `POST auth/resident/signup/` `{email, first_name, last_name?, language_code?}` (no password: it is chosen at the code step) | Always `201`. A new address gets a 6-digit code by email; an address that already has a verified account gets a "you already have an account" email instead. Send an empty hidden `website` field only if you add a honeypot; a real client omits it |
| Verify | `POST auth/resident/otp/email/verify/` `{email, code, password?}` | Returns `{access, refresh}` and marks the email verified, so signup → code → signed in. **Send the `password` the person chose on the code screen of a signup**: it takes effect only on first verification; without it password sign-in stays off until a reset (code sign-in still works). `401 INVALID_OTP` on a wrong/expired code (5 tries per code) |
| Resend a code | `POST auth/resident/otp/email/request/` `{email}` | Always `200`. Also the passwordless sign-in for a verified account |
| Sign in | `POST auth/resident/login/` `{email, password}` | `401` until the address is verified and a password set → send the user to the code screen |
| Forgot password | `POST auth/resident/password-reset/` `{email}` then `POST auth/resident/password-reset/confirm/` `{email, code, new_password}` | Codes, not links. A weak password is rejected **before** the code is spent, so the user can retry the same code |
| Refresh | `POST auth/token/refresh/` | Shared with staff |
| Profile | `GET/PATCH auth/me/` | `tenant` is `null` for a resident |
| Change password | `POST auth/password/change/` | Shared; returns a fresh pair |
| Delete account | `POST auth/account/deletion/` (+ `auth/account/deletion/otp/`) | Shared flow from Module 22. Removes the login and the person's own rows; **the PG's records stay** |

Use `flutter_secure_storage` for tokens, as for staff.

## 2. Getting linked

### A. The person asks (join code)
The PG shows a code (8 characters, e.g. `K7M2Q9XA`; staff see it, with a QR, on the property page). Case and spaces/dashes
are ignored.

1. `GET me/join-codes/{code}/` → `{name, city}`. Show "Is this your PG?" `404 JOIN_CODE_NOT_FOUND` covers an unknown,
   malformed, inactive or blocked PG alike. Needs a **verified** email. 20 lookups/hour.
2. `POST me/link-requests/` `{join_code, message?, claimed_name?, claimed_phone?, claimed_room?}` → `201` (or `200` with
   the existing one: asking twice is safe). `claimed_*` only help staff find the record; nothing is auto-matched.
   `409 RESIDENCY_LINK_EXISTS` if already linked to that PG.
3. Staff review it and approve against a record they choose. You are notified (push + email) of the outcome.
4. `GET me/link-requests/` lists the person's requests (`pending | approved | rejected | cancelled`);
   `POST me/link-requests/{id}/cancel/` withdraws one.

**A join code identifies a PG and nothing else.** Knowing it grants no access.

### B. Staff invite
Staff tap "Invite to app" on a resident (needs the resident's email). The person gets an email with a link
`{FRONTEND_BASE_URL}/join#token=…` (the token is in the fragment so it stays out of logs). Handle it as a deep link:

1. Not signed in → sign up / sign in with **the email the invite was sent to** (verify it).
2. `POST me/invites/accept/` `{token}` → `201 {residency_id, status}` (or `200` if already accepted).
   - `400 INVITE_INVALID` — expired, cancelled, replaced by a newer invite, tampered, or the record is no longer
     eligible. Say "Ask your PG to send a new invitation."
   - `403 INVITE_EMAIL_MISMATCH` — signed in with a different email. Offer to sign out, or to use a join code.
   - `403 EMAIL_NOT_VERIFIED` — verify first.
   - `409 RESIDENCY_LINK_EXISTS` — the record already has app access.
   - **Retrying is safe** and returns the link in its current state, even if staff revoked it meanwhile. It never
     re-grants access.

## 3. Using a residency

`GET me/residencies/` (no extra header) lists every link:

```json
[{"id": "…", "status": "active", "origin": "invite", "scope": "full",
  "business_name": "Sunrise PG", "property_id": "…", "property_name": "Sunrise PG - Madhapur",
  "resident_status": "active", "first_name": "Ravi",
  "activated_at": "…", "exited_at": null, "access_expires_at": null}]
```

`id` is the **residency id**. Module 26b's endpoints take it in the **`X-Residency-Id`** header; send it on every
call that acts inside one PG. Keep a "current residency" in app state and show a switcher when there is more than one.

### `scope` — drive the UI from it, never from the resident's status
| `scope` | Meaning | Show |
|---|---|---|
| `full` | living there | everything |
| `reserved` | booked, not moved in | profile, notices, bills |
| `bills` | has left (within the post-exit window), or the PG's owner is suspended | **only** own invoices, payments, receipts and deposit settlement |
| `none` | revoked, expired, or not a resident | nothing for this PG; say why (`status`) |

A residency with `scope: "bills"` and `exited_at` set should say "Your stay ended on …; you can still see your bills
until `access_expires_at`." Access ends **at that timestamp**, evaluated on every request; there is no background job
to wait for. Calls the scope doesn't allow return `403 RESIDENCY_INACTIVE`. A missing header is
`400 RESIDENCY_REQUIRED`; a link that isn't yours is `403 RESIDENCY_NOT_FOUND` (same answer as "doesn't exist").

## 4. Error codes quick reference
`EMAIL_NOT_VERIFIED`, `INVALID_OTP`, `NO_ACTIVE_ACCOUNT`, `JOIN_CODE_NOT_FOUND`, `INVITE_INVALID`,
`INVITE_EMAIL_MISMATCH`, `RESIDENCY_LINK_EXISTS`, `LINK_REQUEST_NOT_PENDING`, `RESIDENCY_REQUIRED`,
`RESIDENCY_NOT_FOUND`, `RESIDENCY_INACTIVE`, `ACCOUNT_DELETION_PENDING` (a locked account may only see/cancel its
deletion request), plus the usual `429` throttles. Branch on `code`, never on the translated message.

## 5. Not available yet
Bills, receipts, notices, complaints and visitor requests (Module 26b); push for resident accounts (see the spec's
open items: push rows are tenant-scoped and need a decision); phone sign-in (no SMS vendor yet); the invite deep-link
registration (the email link currently opens the website).
