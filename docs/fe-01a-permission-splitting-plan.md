# FE-01a: Role-Based Permission Splitting

> Planning doc for a slice of FE-01 (Auth & shell) — not a full FE-01 delivery.
> Source of truth for route groups, invariants, and stack choices remains
> `docs/frontend-plan.md`. This file only sequences the permission-matrix work.
> Reviewed against the codebase 2026-08-30 — see "Review notes" at the bottom
> for what changed from the original draft and why.

## Background

The backend has a **complete permission matrix** in
[`roles.py`](file:///d:/MYPROJECTS/PG-MANAGEMENT-WEB/backend/apps/core/roles.py)
with **5 roles**: `super_admin`, `owner`, `manager`, `receptionist`, `resident`.

`GET /api/v1/auth/me/` already returns `permissions[]` via `permissions_for(user.role)`
(confirmed in [`MeSerializer`](file:///d:/MYPROJECTS/PG-MANAGEMENT-WEB/backend/apps/accounts/serializers.py#L260-L273) —
no backend change needed).

The frontend currently ignores this: the `(owner)` layout guard checks only
`isLoggedIn` in localStorage, nav items are hardcoded for an owner, and there's
no auth context.

---

## Scope: this is FE-01a, not all of FE-01

Per `frontend-plan.md` §7, FE-01 also covers signup + trial, OTP login, email
verify, password reset, staff accounts + property assignment, and the Manager
property switcher. None of that is in this slice. **Do not mark FE-01 ✅ after
this lands** — update the status board to describe exactly what shipped.

---

## Route groups — decided, not open

`frontend-plan.md` §3.2 already answers the "shared shell vs. separate portals"
question; this is not a live decision for this task:

| Route Group | Allowed Roles | Notes |
|---|---|---|
| `(owner)/` | `owner`, `manager` | Shared shell. Nav + actions filtered by permission matrix. Managers get a property switcher scoped to assigned properties (later slice); Owners see all. |
| `(reception)/` | `receptionist` | **Separate** portal: visitors + read-only resident lookup. Not merged into `(owner)`. |
| `(resident)/` | `resident` | Resident portal, PWA install target. Home route is `/home`, not `/dashboard`. |
| `(superadmin)/` | `super_admin` | Tenants, plan-limit config, platform metrics, overrides. |

This is a correction from an earlier draft that proposed merging `manager` +
`receptionist` into one `(staff)/` group — that contradicts the approved route
map and was never actually decided as an open question in this doc.

`super_admin` must be included in the role guard. A guard that redirects
"anyone who isn't owner/manager/receptionist/resident" will lock out Super
Admin; a guard that redirects "anyone who isn't owner" locks out everyone else.

---

## What Needs To Be Built

### 1. Frontend: Auth Context (`src/features/auth/AuthContext.tsx`) — **[NEW]**

Per `frontend-plan.md` §3.3, `features/<module>/` holds module logic; `lib/`
holds pure helpers. So:

- `src/features/auth/AuthContext.tsx` — the `AuthProvider` + `useAuth()` hook.
  Calls `GET /api/v1/auth/me/` (already implemented as `getCurrentUser()` in
  `lib/api.ts`) once after login/on mount, stores `{ user, permissions,
  isLoading }` in React context (in-memory, not localStorage).
- `src/lib/permissions.ts` — pure `hasPermission(permissions, key)` helper,
  unit-testable without React.

```ts
const { hasPermission } = useAuth();
if (hasPermission('manage_staff_accounts')) { ... }
```

### 2. Frontend: `PermissionGate` component (`src/components/shared/PermissionGate.tsx`) — **[NEW]**

```tsx
<PermissionGate permission="manage_invoices">
  <InvoiceCreateButton />
</PermissionGate>
```

Renders `null` (or a fallback) if the user lacks the permission.

### 3. Frontend: Token/session storage — explicitly still the temporary client

`frontend-plan.md` §3.1 specifies a BFF proxy (`app/api/[...path]/route.ts`)
keeping JWTs in httpOnly cookies, with `proxy.ts` guarding route groups by
role claim **server-side**. That proxy does not exist yet. `lib/api.ts`'s
header comment and the plan's Decisions table both flag the current
localStorage-JWT client as a temporary unblock for module 02 that **must be
replaced** before the app leaves a developer machine.

**Decision for this slice (needs owner confirmation, not assumed here):**
keep the client-side guard on top of the existing localStorage client for
now, and treat the BFF proxy as a separate, explicitly tracked follow-up —
do not record the localStorage approach as the settled design. Add a dated
entry to `frontend-plan.md` §11 Decisions if this is approved, the same way
the module 02 unblock was recorded.

While in this client, also fix the existing logout bug:
`SideNav.tsx`'s sign-out handler only removes `isLoggedIn` and leaves
`accessToken`, `refreshToken`, `userRole`, `userName` behind — a live
invariant F7 (tenant data never leaks across sessions) violation. It should
call the existing `clearSession()` from `lib/api.ts`, which already clears
all of those keys.

### 4. Frontend: Route Guard Update

`(owner)/layout.tsx` currently:
```ts
if (localStorage.getItem("isLoggedIn") !== "true") router.push("/login")
```

Replace with a role-aware guard using `AuthContext`:
- Wraps the layout in `AuthProvider`.
- Waits for `/auth/me/` to resolve before rendering.
- Redirects to `/login` if no valid session.
- Redirects `owner`/`manager` in; redirects every other role to their own
  group's home (`resident` → `/home`, `receptionist` → the `(reception)`
  home, `super_admin` → the `(superadmin)` home).

`(reception)/layout.tsx` and `(resident)/layout.tsx` need their own
role-scoped guards (new files, minimal for this slice — reuse `AuthProvider`,
don't duplicate the fetch).

### 5. Frontend: Permission-Filtered Nav (`NavItems.ts` → `NavItems.tsx`)

Convert to a `useNavItems()` hook reading `useAuth()`. Corrected permission
mapping (fixes vs. the original draft):

| Nav item | Route | Required permission |
|---|---|---|
| Dashboard | `/dashboard` | *(always visible once logged in, owner/manager only — resident's equivalent is `/home` in its own group)* |
| Properties | `/properties` | `manage_properties` |
| Residents | `/residents` | `manage_residents` |
| Complaints | `/complaints` | `manage_complaints` |
| Financials | `/financials` | `manage_invoices` |
| Settings | `/settings` | `manage_tenant_settings` |
| Profile | `/profile` | *(always visible — every role needs their own profile)* |

Notes:
- `/profile` was missing from the original mapping; it must not be
  permission-gated at all.
- `Settings` here is the **tenant-level** settings page
  (`GlobalSettings.tsx`, gated `manage_tenant_settings` = owner only). The
  **per-property** settings page (module 03, `manage_property_settings` =
  owner + manager) is a different screen — don't conflate the two when
  wiring `PermissionGate`.
- `BOTTOM_NAV_ITEMS` currently links a 4th slot to `/more`, which has no
  route. Out of scope for this slice — flag it, don't invent the route.

### 6. Frontend: Login redirect by role (`LoginForm.tsx`)

`login()` in `lib/api.ts` **already** calls `/auth/me/` after token storage
and mirrors `role`/name into localStorage — this part doesn't need building,
only extending. Add role-based redirect after `login()` resolves:

- `owner`, `manager` → `/dashboard`
- `receptionist` → the `(reception)` group's home
- `resident` → `/home` (not `/resident/dashboard` — route groups don't
  appear in the URL, and the resident group's home route is `/home` per
  `frontend-plan.md` §3.2)
- `super_admin` → the `(superadmin)` group's home

### 7. Frontend: `SideNav` user info footer

Replace the hardcoded `"Owner Portal / Premium Plan"` footer (`TODO(FE-13)`
in `SideNav.tsx`) with real user data from `AuthContext`: display name, role
badge, and plan name.

### 8. Backend: No changes needed

Verified, not assumed: `MeSerializer.get_permissions()` already returns
`permissions_for(obj.role)` on `GET /auth/me/`.

---

## Proposed file changes

### Auth Layer
- **[NEW]** `frontend/src/features/auth/AuthContext.tsx`
- **[NEW]** `frontend/src/lib/permissions.ts`
- **[NEW]** `frontend/src/components/shared/PermissionGate.tsx`

### Route Guards
- **[MODIFY]** `frontend/src/app/(owner)/layout.tsx`
- **[NEW]** `frontend/src/app/(reception)/layout.tsx`
- **[NEW]** `frontend/src/app/(resident)/layout.tsx` (minimal — home page itself is a later slice)

### Navigation
- **[MODIFY]** `frontend/src/components/shared/NavItems.ts` → `NavItems.tsx`
- **[MODIFY]** `frontend/src/components/shared/SideNav.tsx` — filtered nav, real footer, fixed logout (`clearSession()`)
- **[MODIFY]** `frontend/src/components/shared/BottomNav.tsx` — filtered items

### Login Flow
- **[MODIFY]** `frontend/src/features/auth/LoginForm.tsx` — redirect by role

---

## Testing gap — flag, don't silently skip

`frontend-plan.md` §8 requires Vitest + RTL unit tests and a Playwright role
test ("a Receptionist cannot reach billing routes and a Manager cannot see
unassigned properties"). Neither Vitest nor Playwright test infra is wired
into `package.json` yet (`playwright` is a devDependency but no test files or
config exist). Options:
1. Install Vitest + RTL as part of this slice and write the unit tests it
   unlocks (`hasPermission`, `PermissionGate`, nav filtering).
2. Explicitly defer automated tests and rely on the manual plan below,
   recording that as a gap in the FE-01 status board line — not silently.

Recommend (1) for at least `lib/permissions.ts` and `PermissionGate`, since
they're pure/isolated and cheap to test; defer Playwright role tests until
`(reception)`/`(resident)` pages have real content to navigate to.

### Manual Verification
1. Log in as **owner** → full nav (Dashboard, Properties, Residents,
   Complaints, Financials, Settings, Profile).
2. Log in as **manager** → nav without Settings; cannot access `/settings`
   (still has property-level settings via `manage_property_settings`).
3. Log in as **receptionist** → lands in `(reception)` group, not `(owner)`.
4. Log in as **resident** → redirected to `/home` in `(resident)` group.
5. Log in as **super_admin** → redirected to `(superadmin)` group.
6. SideNav footer shows actual user name + role.
7. Logout via SideNav clears `accessToken`, `refreshToken`, `isLoggedIn`,
   `userRole`, `userName` (all four keys, not just `isLoggedIn`); revisiting
   a protected route redirects to `/login`.

---

## Review notes (2026-08-30)

Corrected from an earlier draft that:
- Proposed merging `manager` + `receptionist` into a `(staff)/` group as an
  open "Option A vs B" choice — `frontend-plan.md` §3.2 already assigns
  Receptionist to its own `(reception)/` group; this wasn't actually an open
  question.
- Omitted `super_admin` entirely (4 roles listed instead of 5).
- Described the localStorage JWT client as settled infrastructure to build
  on top of, without flagging that `frontend-plan.md` records it as a
  temporary unblock that must be replaced by the §3.1 BFF proxy, and that
  §3.1 specifies *server-side* route-group guards via `proxy.ts` — this slice
  only does client-side guards, which is a narrower interim than the approved
  design and should be called out, not silently substituted.
- Said FE-01 auth already "persists JWT tokens in localStorage (already done
  by api.ts)" as if that were the target state, rather than the flagged
  shortcut.
- Missed `/profile` in the nav permission table, and had the resident
  redirect target wrong (`/resident/dashboard`, which doesn't exist under
  Next.js route groups — the real target is `/home`).
- Didn't mention the existing logout bug (`SideNav.tsx` only clears
  `isLoggedIn`, not the other session keys) even though this slice touches
  that exact file.
- Verification plan had no automated tests, despite `frontend-plan.md` §8
  requiring them.
