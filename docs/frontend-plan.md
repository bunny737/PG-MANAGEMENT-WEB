# Frontend Plan — Next.js Web App + PWA

> Status: Approved by owner on 2026-07-02 (supersedes the earlier "backend only" rule in CLAUDE.md)
> Source of truth for all frontend work. Read alongside `pg_hostel_management_prd_v2.md` and `modules/README.md`.

---

## 1. Scope

A single Next.js web application serving all five roles (Super Admin, Owner, Manager,
Receptionist, Resident), installable as a PWA on Android/iOS/desktop. This is the primary
UI for MVP.

Client build order: **Web/PWA (this doc) -> Flutter (Android + iOS together).** The PWA
covers the mobile-first resident experience until the Flutter app ships. Flutter targets
both platforms from one codebase — owner decision 2026-09-17, superseding the earlier
native-Android-then-native-iOS plan (2026-07-05; see the Decisions table). The Flutter
app is a client of the same Django REST API described here — see §3.1a — so no backend
or API redesign is needed to add it.

The frontend is a pure API client. All business rules (billing math, status transitions,
plan limits, penalties) live in the Django backend. The frontend renders, validates input
shape, and never re-implements money logic.

---

## 2. Stack

| Concern | Choice | Notes |
|---------|--------|-------|
| Framework | Next.js 16 (App Router) + React 19 + TypeScript (strict) | PRD says "Next.js 14" — written June 2026; scaffolded 2026-07-03 on current stable (16.x had shipped by then — same "don't start new on an old major" reasoning as the original 15 call, see Decisions §11) |
| Styling | Tailwind CSS v4 + shadcn/ui | Noto Sans via `next/font` (Indic script coverage per PRD i18n) |
| Server state | TanStack Query v5 | All API reads/writes; cache invalidation per module key |
| Client state | Zustand (minimal) | Only UI state: active property, sidebar, dialogs |
| Forms | React Hook Form + Zod | Zod schemas mirror DRF serializer shapes |
| Tables | TanStack Table | Residents, invoices, payments, audit logs |
| Charts | Recharts | Occupancy trend, financial dashboard |
| i18n | next-intl | Deviation from PRD's next-i18next — see Decisions §11 |
| PWA | Serwist (`@serwist/next`) | Deviation from unmaintained next-pwa — see Decisions §11 |
| API types | drf-spectacular (backend) → `openapi-typescript` codegen | Generated client types; no hand-written response interfaces |
| Testing | Vitest + React Testing Library; Playwright (E2E); Lighthouse CI | PWA + a11y audits gated in CI |
| Lint/format | ESLint + Prettier; `eslint-plugin-i18next` style rule to forbid literal JSX strings | Enforces invariant F2 below |

Repo layout: `frontend/` directory at repo root, sibling of `backend/`. Dockerized
alongside the existing `docker-compose.yml` (Next.js standalone output behind Nginx).

---

## 2.1 Visual design system

Reference mock: mobile Owner dashboard (Occupancy + Financials + Active Issues
cards, bottom tab bar). Tokens below are implemented as Tailwind v4 `@theme`
variables in `src/app/globals.css` — components consume the token names, never
raw hex, so retheming is a one-file change.

### Colors (light mode — the only mode targeted for MVP; tokens are CSS
variables so a dark variant is a later addition, not a rewrite)

| Token | Hex | Use |
|-------|-----|-----|
| `--color-surface-page` | `#F8FAFC` | App background |
| `--color-surface-card` | `#FFFFFF` | Default card background |
| `--color-surface-inverse` | `#1E293B` | Dark feature card (Financials) |
| `--color-border` | `#E2E8F0` | Card borders, dividers, progress-bar track |
| `--color-ink` | `#0F172A` | Primary text |
| `--color-ink-muted` | `#64748B` | Secondary text |
| `--color-ink-faint` | `#94A3B8` | Small uppercase labels, placeholder text |
| `--color-ink-inverse` | `#FFFFFF` | Text on `surface-inverse` |
| `--color-ink-inverse-muted` | `#94A3B8` | Secondary text on `surface-inverse` |
| `--color-accent` | `#2563EB` | Primary actions, active nav, links, progress fill |
| `--color-accent-hover` | `#1D4ED8` | Accent hover/pressed |
| `--color-accent-soft` | `#EFF6FF` | Accent tint background (outline button fill on hover, soft icon bg) |
| `--color-status-good` | `#16A34A` | Positive deltas ("+5.2% vs last month") |
| `--color-status-critical` | `#DC2626` | Text for critical status |
| `--color-status-critical-soft` | `#FEE2E2` | Pill/badge background for critical status |

Status colors always ship with a text label or icon next to them (never color
alone — e.g. "Open", "3 High Priority"), per the dataviz skill's status-color
rule. They are not used as an adjacent categorical set, so no CVD-pair check
applies; each was checked standalone for text contrast against its own
background. The Occupied/Vacant figure is a single-measure fill (accent on a
border-colored track), not a 2-series categorical chart, so it's a stat tile,
not a chart requiring palette validation.

### Typography, shape, elevation

- **Font**: Noto Sans via `next/font/google` (already required for Indic
  script coverage, §6/§11) — do not add a second display font.
- **Numerals**: large stat numbers are bold, tabular (`font-variant-numeric:
  tabular-nums`) so figures don't jitter as they update.
- **Radius**: cards `rounded-2xl` (16px), buttons/inputs `rounded-xl` (12px),
  pills/badges `rounded-full`.
- **Elevation**: cards use a soft single shadow (`shadow-sm` on white cards,
  `shadow-md` on the inverse Financials card) — never more than one shadow step.
- **Spacing**: card padding 20px (`p-5`), inter-card gap 16px (`gap-4`).

### Component patterns (`components/shared/`)

- `StatTile` — uppercase faint label + bold large number + optional muted
  sub-line (e.g. a percentage). Used for occupancy figures.
- `ProgressBar` — single-hue accent fill on a `--color-border` track; used for
  occupancy, never for multi-segment data (that would need a categorical
  palette instead).
- `MoneyStat` — muted uppercase label + large bold amount + optional
  `StatusDelta` (colored ↗/↘ + percentage, `status-good`/`status-critical`).
  Renders the string amount from the API verbatim per invariant F1 — no
  strikethrough-to-imply-waived styling (a version of this mock used
  strikethrough on an outstanding-dues figure; dropped as a real-money UX risk
  — a struck-through amount owed reads as "waived," which the backend hasn't
  said). Colour (not strikethrough) still marks it as attention-worthy.
- `StatusPill` — `status-critical-soft` bg + `status-critical` text + label;
  reused for row-level status (`Open`) and card-level counts (`3 High Priority`).
- `BottomNav` (< `md`) / `SideNav` (`md`+) — two distinct reference designs,
  not one design reflowed. Owner supplied a phone mock (tab bar, single
  stacked column, `Add Resident`/`Generate Invoices` quick actions) and,
  2026-07-03, a separate desktop mock (persistent sidebar with 5 sections,
  page-header pattern, denser multi-column grid, an activity feed) — the
  earlier "match the phone mock at every width, no sidebar" call (also
  2026-07-03) is superseded by the desktop mock arriving. `BOTTOM_NAV_ITEMS`
  (4 slots, capped with a `More` catch-all) and `SIDEBAR_NAV_ITEMS` (5, one
  per section) are separate lists in `NavItems.ts` — both still driven by the
  permission matrix from `/auth/me/` (F8), not hardcoded per role, once FE-01
  wires real auth. Active state also differs deliberately: bottom nav uses a
  filled `accent` pill (mobile tab-bar convention); sidebar uses a subtle
  `surface-page` row highlight (desktop nav convention) — not a mismatch to
  fix later.
- `DashboardHeader` (mobile: compact brand + bell) vs. `DesktopHeader` (page
  title + subtitle + bell-with-unread-dot + `Add Resident`) — the desktop mock
  drops the second `Generate Invoices` quick action entirely; revisit if the
  owner wants it back once FE-08 exists.
- `TodaysActivity` — activity-feed preview (icon avatar + emphasized-name text
  + timestamp) previewing FE-16's activity timeline. Icon tint is chosen from
  the item's semantic `tone` (info/good/neutral → accent/status-good/neutral
  tokens), not a per-item hue, to keep the feed on the same restrained palette
  as the rest of the dashboard — the reference mock's orange visitor-icon tint
  was dropped for this reason.

## 3. Architecture

### 3.1 API integration — BFF proxy with httpOnly cookies

- Browser never sees JWTs. Next.js Route Handlers under `app/api/[...path]/route.ts`
  proxy every call to Django (`/api/v1/...`).
- Access token (15 min) + refresh token (7 days) stored in `httpOnly; Secure; SameSite=Lax`
  cookies set by the proxy. Proxy transparently refreshes on 401-expired and retries once.
- Refresh failure, account suspension (`403 SUBSCRIPTION_SUSPENDED`), or force-logout →
  proxy clears cookies, client redirects to `/login` with a translated reason banner.
- Next.js `proxy.ts` (renamed from `middleware.ts` in Next 16 — same mechanism)
  guards route groups by role claim (decoded server-side only); the API remains
  the real authority — this is UX, not security.
- Same-origin API calls mean no CORS config and the service worker can apply cache
  strategies uniformly.

**Built 2026-10-19** (`feature/pwa-ios`). Route handlers: `app/api/auth/{login,login-phone,login-email-otp,logout}`
(set/clear `pg_access` + `pg_refresh`, both `HttpOnly`, path `/api`, lifetimes read from each
token's `exp`; and a secret-free `pg_session` marker on path `/` so `proxy.ts` can bounce signed-out
page navigations, which never carry the `/api`-scoped cookies) and `app/api/[...path]` (everything
else under `/api/v1/`). Behaviours worth knowing:

- Login handlers return only the `/auth/me/` payload. The token-issuing endpoints
  (`auth/login`, `login-phone`, `token/refresh`, `otp/verify`, `otp/email/verify`, `password/change`) are **404 through the
  generic proxy**, so a proxied call can never hand a token to page JS. Email-code login (2026-10-21) goes
  through its own handler, `login-email-otp`; its request step (`otp/email/request`) issues no tokens and uses
  the generic proxy. Phone OTP still needs its own handler when SMS delivery is built.
- Change password (2026-10-21) has its own handler, `app/api/auth/change-password`, because Django ends every
  session when a password changes and answers with a fresh token pair. The handler (`lib/server/authenticatedUpstream.ts`)
  calls Django as the signed-in user with the same refresh rules as the proxy, installs the new pair in the
  httpOnly cookies and returns a token-free `{ok: true}` (no follow-up `/auth/me/` that could fail and strand
  the new session). A 400/429 leaves the session as it was; only a definitive 401 clears the cookies.
- Forgot/reset password (2026-10-21): `/forgot-password` (always answers "if an account exists…") and
  `/reset-password` (the emailed link carries `uid`+`token`, plus `invite=1` for staff, in the URL **fragment**,
  stripped on load like `/verify-email`) go through the generic proxy; neither signs anyone in. The new-password
  minimum (8) applies to signup, reset, invite and change only — sign-in accepts any non-empty password. `/login?view=staff|owner`
  skips the role chooser (the landing spot after a staff invite).
- Refresh is server-side. With no access cookie (it expired) the proxy refreshes **before** sending,
  so the request runs once; with an access cookie it is replayed only after the backend answered
  401 (which means it did not run). A request is therefore never executed twice — this matters for
  anonymous writes (signup, OTP request, password reset), which carry a stale refresh cookie for
  some users. Only a definitive rejection (401/403 from the refresh endpoint) clears cookies; an
  unreachable backend is a 502 and does **not** log the user out. If the refresh was rejected, a
  public endpoint still runs (anonymously, once) and an authenticated one returns 401 with the
  reason (e.g. suspended).
- The body is buffered once (so a refresh-replay can resend uploads) but **bounded**:
  `BFF_MAX_BODY_BYTES` (default 10 MB) is enforced from the declared `Content-Length` and again
  while streaming, so a chunked body with no length cannot grow the Node process's memory; login
  bodies are capped at 16 KB. The backend has no upload limit of its own beyond Django's defaults,
  so this is the effective ceiling — keep nginx's `client_max_body_size` at or above it. The client treats any 401 from the proxy as
  "session over" (`clearSession()` + redirect). The translated suspension reason banner is not
  built yet.
- Writes whose `Origin` is not this app's are rejected (defence in depth on top of `SameSite=Lax`).
- `next.config.ts` sets `skipTrailingSlashRedirect` — Django's routes end in `/` and a POST cannot
  follow `APPEND_SLASH`.
- **Deployment requirements:** the edge (nginx) must *overwrite* `X-Forwarded-For` rather than append to
  a client-supplied one — the proxy forwards it and `apps/audit/log.py:client_ip` (invariant 9) and
  login throttling both trust the first entry. `INTERNAL_API_URL` must point at Django, and
  `ALLOWED_HOSTS` must include the host name the proxy uses (`backend` in compose).
- Push token handling around logout (`lib/push.ts`). The push token belongs to the browser, not the
  account, and logout only waits 3 s for cleanup, so the next account can start while the previous
  account's calls are still running. A timeout cannot cancel an in-flight SDK call, so:
  - Registration and revocation run through one **serialized queue**, and each operation is capped at
    10 s (from when it starts) for both the queue and the promise the caller awaits — a hung
    `deleteToken()` makes `disablePush()` move on to the server-side DELETE.
  - Registration is **cooperatively cancelled**: it records a session generation and the signed-in
    tenant+user, re-checks both after each await, and abandons itself with no POST and no storage
    write if the session ended or changed. `disablePush()` bumps the generation first, even with
    nothing stored yet.
  - **Conditional row delete:** aborting the 5 s DELETE does not recall a request the server already
    has, and the same account re-enabling push gets the same row id back from the upsert, so the
    client stores the row's `last_seen_at` and sends it as `?if_last_seen_at=` (server: 412 and no
    delete if the row was registered again since; see module 14 Decisions). The request is also
    aborted with an `AbortController` at the bound.
  - **Order rule:** revoking the browser token never waits on a call to our own backend. In both
    `disablePush()` and the late-POST cleanup the token is revoked first, and the server-side row
    DELETE comes last and is bounded to 5 s (`apiFetch` has no timeout of its own), so a stalled or
    unreachable backend can neither keep a previous user's token alive nor leave the "turn off"
    button busy forever.
  - A revocation abandoned by the cap that finishes late, after a newer registration began,
    re-registers to repair it. The repair is **queued** (`queueRegistrationRepair`) and decides
    whether push is "on" only once it reaches the head of the queue, i.e. after any registration still
    in flight has stored its row; deciding at once would see an empty store, do nothing, and leave
    that registration holding a revoked token.
  - A registration whose **POST was already in flight** when the session ended (logout finds nothing
    stored to remove, so it cannot clean up) cleans up after itself when the response arrives: if no
    newer registration exists it revokes the browser's FCM token — taking over by a later user is not
    enough, since nobody may ever opt in on a shared browser — and only then tries to delete the row
    (which only works while that user's cookies are still valid; otherwise the row dies with its
    token on the backend's next send). If the next user did opt in, the token is theirs and is NOT revoked;
    instead their session registers again, because the late POST made the endpoint reassign the
    token back to the previous user. In that case the stale row is also NOT deleted: the backend
    upserts on the token, so the same account turning push off and on again gets the same row id back,
    and a late DELETE would remove its current subscription. The cleanup is fenced by the registration
    epoch and queued behind the running operation (awaiting it inside would wait on itself).
- Known limitation: an *offline* logout clears local state but the cookies stay until the next
  login (the logout request cannot be sent).

### 3.1a Mobile client (Flutter, Android + iOS)

The BFF proxy above is a **browser-only** mitigation (keeps JWTs out of reach of
in-page JS/XSS). It does not apply to the Flutter app — it calls
`/api/v1/...` on Django directly, the same endpoints and serializers the web
app uses, with no proxy layer:

- Auth: same `POST /api/v1/auth/login/` -> `{access, refresh}` and
  `POST /api/v1/auth/token/refresh/` flow as the web temporary client
  (`frontend/src/lib/api.ts`), just called from Dart (`dio`/`http`) instead
  of `fetch`. A phone+password path (`POST /api/v1/auth/login-phone/`) was
  added for Manager/Receptionist accounts that have no email, plus
  `auth_version`-based immediate token revocation on password change —
  both covered in `docs/auth-staff-flutter-integration.md`.
- Token storage: `flutter_secure_storage` (Android Keystore-backed on
  Android, Keychain-backed on iOS — one API, platform-correct storage on
  both). Never plain `SharedPreferences`/local files — that's the mobile
  equivalent of the `localStorage` shortcut the web client uses temporarily
  and must not be repeated on a permanent mobile client.
- No CORS concerns (native HTTP clients aren't subject to browser CORS), so
  this needs no backend config beyond what already exists for the web app.
- Versioning/response shape: the `/api/v1/` prefix and DRF serializer JSON
  already used by web work unchanged for mobile. If a mobile-only response
  shape is ever needed, version it (`/api/v2/`) rather than branching
  behavior in existing serializers — not needed yet.
- Push notifications: the backend (`POST/GET/DELETE
  /api/v1/notifications/push-subscriptions/`, Module 14 V2) and the Flutter
  side (`firebase_messaging` setup, permissions, token lifecycle) are both
  covered in `docs/push-notifications-integration.md`.
- Biometric unlock and offline write queues remain mobile-app concerns to
  design when Flutter work actually starts — not addressed by this doc,
  which scopes web only.

### 3.2 Route map (App Router route groups)

```
app/
├── (marketing)/                Public site at pglive.in — `/` landing, features, pricing, app (QR target),
│                               contact, privacy, terms (§12). Server-rendered, no session required.
├── (auth)/                     login, signup (tenant onboarding + 45-day trial),
│                               verify-email, otp, forgot-password, reset-password
├── (owner)/                    Owner, Manager, and Receptionist portal (nav filtered by permission matrix)
│   ├── dashboard/              occupancy + financials from analytics/summary/ (D1), per-section state rule
│   ├── properties/[id]/        D2 bed-grid overview (stats, dues banner, month nav, building/floor tabs, filters, legend)
│   │   ├── buildings/…/rooms/…/beds/[bedId]   the existing nested CRUD path (add/edit, D9 allowed_transitions)
│   │   ├── settings/           Module 2B: transfer rent timing, penalty config
│   │   └── features/           Module 18: what the PG offers (catalogue + own features)
│   ├── residents/[id]/         profile, documents, D6 finance card (replaces the old dead-field Financials tab), maintenance
│   ├── admissions/             pipeline: Inquiry → Visit → Reserved → Admission → Check-in
│   ├── allocations/            bed board, temporary-allocation list, transfers
│   ├── billing/                tabs: Invoices, Payments, Cash movements, Discounts (replaces the mock /financials)
│   │   ├── invoices/[id]/      line-item detail (F6), draft edit/issue/delete, record payment
│   │   └── payments/[id]/      receipt (JSON view, PDF download, Web Share)
│   ├── expenses/               D5: month nav, category chips from expenses/summary/, add/edit sheet, categories
│   ├── deposits/               notice period, vacating wizard, absconded flow
│   ├── complaints/             status board, comment threads
│   ├── visitors/               log, check-in, check-out (Owner, Manager, Receptionist)
│   ├── staff/                  Owner only: Manager/Receptionist accounts; `staff/[id]` = per-person module access + PG access
│   ├── reports/                D1/D7: Overview/Collections/Occupancy/Exports tabs, 6-month trend chart
│   └── subscription/           Owner only: plan usage, upgrade via Razorpay, billing history
├── (resident)/                 Resident portal (primary PWA install target)
│   ├── home/  invoices/  receipts/  complaints/  visitors/  notices/  profile/
├── (superadmin)/               tenants, plan-limit config, platform metrics, overrides
├── api/[...path]/              BFF proxy to Django
├── manifest.ts                 PWA manifest
├── ~offline/                   offline fallback page
└── sw.ts                       Serwist service worker
```

Owner, Manager, and Receptionist share the `(owner)` portal (receptionist folded in per 2026-10-11 decision): navigation and actions are filtered by the
permission matrix (PRD §6) fetched from the backend `/auth/me/` at session start — never inferred
client-side from role names. Receptionist sees only visitor management and read-only property/resident
views. Super Admin and Resident logins into this portal are explicitly rejected. Managers see a **property switcher** scoped to assigned
properties; Owners see all properties.

### 3.3 Frontend directory conventions

```
frontend/src/
├── app/                  routes only — thin pages composing features
├── features/<module>/    components, hooks, api calls, zod schemas per module
│                         (auth, properties, residents, admissions, allocations,
│                          discounts, billing, payments, deposits, complaints,
│                          visitors, subscription, audit, timeline, export)
├── components/ui/        shadcn primitives
├── components/shared/    StatusBadge, MoneyText, PropertySwitcher, LimitGate,
│                         AuditDiff, TimelineList, EmptyState, OfflineBanner
├── lib/                  api client, query keys, auth helpers, formatters
└── messages/<locale>/    auth.json, residents.json, billing.json, ... (per module)
```

---

## 4. Frontend invariants (mirror of the 10 backend invariants)

F1. **Money is a string.** DRF Decimal serializes as string — keep it a string end to end.
    Display via `MoneyText` (Intl.NumberFormat, `en-IN`, INR). **No arithmetic on money in
    the frontend** — totals, balances, refunds, penalties always come from the API.
F2. **No hardcoded UI strings.** Every label through next-intl `t()` from day one. Lint
    rule blocks literal JSX text. Language switcher shipped in MVP; English and Telugu
    active (owner decision 2026-08-11 — Telugu pulled forward from V2), others
    selectable-but-disabled until translated.
F3. **Statuses are exact and translated by key.** `StatusBadge` maps the backend status
    enum → i18n key + color. Unknown status renders as-is with a neutral badge, never crashes.
F4. **Plan limits come from the API.** Never hardcode 60/5/caps. `LimitGate` reacts to
    `409 PLAN_LIMIT_REACHED` responses by showing the upgrade prompt with plan comparison
    fetched from `/api/v1/subscriptions/plans/`.
F5. **contracted_rent is what residents see.** Billing screens display contracted rent and
    discount as separate lines exactly as the invoice line items list them. Rack rates
    appear only in room/bed management screens.
F6. **Invoices render a list of line items.** The invoice detail component iterates
    `line_items[]` — no fixed "rent + food" layout. Add-ons (V2) render with zero changes.
    Admission form includes an "Add-on Services" section, hidden in MVP (PRD Module 9).
F7. **Tenant data never leaks across sessions.** On logout or tenant/user switch: clear
    TanStack Query cache, Zustand stores, service-worker runtime caches, and IndexedDB.
    Today that also means the cached permission list and any `featureDraft:*`
    sessionStorage entries (Module 18) — both cleared in `clearSession()`.
F8. **The frontend never invents transitions.** Action buttons (vacate, abscond, blacklist,
    waive penalty) appear only when the API's serialized `allowed_actions` / permission
    matrix says so.

---

## 5. PWA plan

### 5.1 Baseline (MVP)

- **Manifest** (`app/manifest.ts`): standalone display, portrait, theme/background colors,
  192/512 icons + maskable variants, `start_url: /login?source=pwa` (not `/`, which is the public
  marketing page since 2026-10-18, §12); `/login` forwards an already-signed-in user to their first
  allowed screen after verifying the session with the API.
  The precache, offline fallback and tenant-scoped runtime caches exclude every `(marketing)` route.
- **Service worker** via Serwist:
  - Precache: app shell, fonts, offline fallback page.
  - `CacheFirst` — hashed Next.js static chunks, fonts.
  - `StaleWhileRevalidate` — images, icons.
  - `NetworkFirst` (3s timeout, 5-min max age) — API **GET**s only, so recently viewed
    dashboards/lists/invoices remain readable offline.
  - **Mutations are never cached or queued in MVP.** Money-touching writes (payments,
    invoices, deductions) must not risk replay/conflict. Offline = read-only, with a
    persistent `OfflineBanner`. Background Sync queue is a V2 item, non-money modules first.
- **Install UX**: capture `beforeinstallprompt` for a custom "Install app" button; iOS gets an
  instructions sheet (Share -> Add to Home Screen; in-app browsers such as WhatsApp are told to open
  Safari). Built for the staff app: an `InstallCard` on the More screen plus a dismissible one-time
  nudge on the dashboard. The resident portal does not exist yet. iOS splash images are not generated yet (see the FE-P1 status row).
- **Cache hygiene** (invariant F7): the worker cannot read httpOnly cookies, so the page tags each
  API request with `X-Cache-Scope: <tenant>_<user>` (`lib/cacheScope.ts`) and the worker keeps one
  `api-<scope>` cache per user, caching nothing for untagged requests. Logout deletes every cache
  except the tenant-free ones (precache, `next-static`, `app-images`) so the shell still opens offline.
  Proxy responses are `Cache-Control: no-store`; redirects and file downloads are never cached.
- **CI gate**: Lighthouse PWA installability + performance budget on the resident portal
  and owner dashboard. **Not built yet.**
- **Built 2026-10-19:** manifest + icons (PGLive brand files in `public/icons/`), Serwist worker
  (`app/sw.ts`), manual registration with an "update available" toast, `OfflineBanner`, translated
  `/~offline` fallback, iOS safe-area/`dvh`/16px-input fixes, share-sheet downloads in an installed
  iOS app. Offline reads are served by `NetworkFirst` (3 s timeout) for `/api/v1/*` GETs (5-minute max
  age, a named constant in `sw.ts`) and for page documents (shell only, no tenant data).

### 5.2 V2

- ~~Web Push notifications~~ — **pulled into MVP 2026-10-19 and built** (iOS PWA stopgap). Backend:
  `POST/GET /api/v1/notifications/push-subscriptions/`, `DELETE .../{id}/`
  (`docs/modules/14-notifications.md`, `docs/push-notifications-integration.md` §6). Frontend:
  `lib/push.ts`, `features/notifications/` (opt-in card on More, foreground toast), worker tap
  handler in `sw.ts`. Today only Owner/Manager/Receptionist can receive pushes (residents have no
  login yet), and on iPhone only from the installed app on iOS 16.4+.
- Background Sync for non-money mutations (complaints, visitor requests).
- Periodic background refresh of the resident's own invoice list.

---

## 6. i18n plan

> Detailed implementation plan — current-state audit, phased build P0–P8, decisions
> and risks — lives in [frontend-i18n-plan.md](frontend-i18n-plan.md). As of
> 2026-08-10 the backend i18n plumbing is complete and the **frontend has none of
> this built yet**; every component still uses literal JSX strings.

- next-intl with **cookie-based locale** (no `/en/` URL prefix — this is an authed
  dashboard, not SEO content). Locale = user profile `language_code`, editable in
  profile settings; tenant default applies to new accounts (PRD §11).
- Message files per module per locale in `messages/<locale>/<module>.json`. English
  complete in MVP; `hi`, `te` (V2) and `ta`, `ml` (V3) add JSON files only — zero code.
- Dates via `Intl.DateTimeFormat` through next-intl formatters; money per invariant F1.
- PDF invoices/receipts are rendered by the backend in the user's language — the frontend
  only downloads them (never generates documents client-side).

---

## 7. Build order & phases

Frontend module work starts only when the matching backend module is ✅ in
`modules/README.md`. FE-00 can start immediately against MSW (Mock Service Worker)
mocks derived from the OpenAPI schema.

### FE-00 — Foundation (parallel with backend 01)
Scaffold (`create-next-app`, TS strict, Tailwind, shadcn/ui, next-intl, Serwist),
BFF proxy skeleton, design tokens, shared components, MSW mock layer, CI
(typecheck, lint, unit, Lighthouse), Docker + Nginx wiring.

### FE-1 — Skeleton (mirrors PRD Phase 1, backend modules 01–06)
| FE task | Needs backend | Contents |
|---------|--------------|----------|
| FE-01 Auth & shell | 01 | signup + trial, login (email/pw, OTP), verify, reset, role-based nav shell, staff accounts + property assignment, property switcher |
| FE-02 Property setup | 02 | property CRUD, floor/room/bed builder, bed grid with statuses, rack rates (with/without food, per-bed override) |
| FE-03 Property settings | 03 | transfer rent timing, penalty type/value/grace/compounding forms |
| FE-04 Residents | 04 | list + status filters, profile, document upload (via BFF → GCS signed URLs), blacklist warning on re-registration |
| FE-05 Admissions | 05 | pipeline board, admission form (billing mode, food preference, contracted rent snapshot display, advance, first-month note, hidden add-ons section) |
| FE-06 Allocations | 06 | bed allocation, temporary-allocation badge + dedicated list, transfer flow showing `rent_effective_date` from property setting |
| FE-D1 Occupancy dashboard | 02, 06 | beds total/occupied/vacant/reserved, trend, temp-allocation flags |

### FE-2 — Money (mirrors PRD Phase 2, backend modules 07–10)
| FE task | Needs backend | Contents |
|---------|--------------|----------|
| FE-07 Discounts | 07 | per-resident discount CRUD (type, reason, validity, approver), discount report |
| FE-08 Billing | 08 | invoice list/detail (line-items iteration), bulk generation, draft→issue, penalty lines + waive-with-note, PDF download |
| FE-09 Payments | 09 | record payment (mode, partials), receipts, outstanding dues dashboard |
| FE-10 Deposits & exit | 10 | notice flow, vacating wizard (inspection → deduction → refund), absconded flow (forfeit → write-off → blacklist confirm) |
| FE-D2 Financial dashboard | 08, 09 | collected, outstanding, discounts given, advances held |

### FE-3 — Operations & launch (mirrors PRD Phase 3, backend modules 11–17)
| FE task | Needs backend | Contents |
|---------|--------------|----------|
| FE-11 Complaints | 11 | raise w/ photo, category/priority, status workflow, comments |
| FE-12 Visitors | 12 | reception log entry/exit, approvals, resident visitor requests, history |
| FE-13 Subscription | 13 | trial banner + day-45/55 states, plan usage, Razorpay checkout (upgrade/downgrade), billing history, suspension lock screen; Super Admin portal (tenants, config-driven limits, overrides) |
| FE-14 Notifications | 14 | notification preferences (email MVP) |
| FE-15 Audit logs | 15 | filterable viewer with before/after diff |
| FE-16 Timeline | 16 | per-resident chronological timeline component |
| FE-17 Export | 17 | CSV/Excel/PDF export buttons (synchronous — exports have no async job status) |
| FE-20 Expenses | 20 | month navigator, category chips, add/edit sheet (idempotent create + attachment), category manager |
| FE-21 Reports / Analytics | 21 | Overview/Collections/Occupancy/Exports tabs, 6-month trend chart (D0/D1/D7) |
| FE-P1 PWA hardening | — | offline fallback polish, install prompts, cache purge audit, Lighthouse pass |
| FE-R1 Resident portal | 04, 08, 09, 11, 12 | resident-facing home, invoices, receipts, complaints, visitor requests, notices |

### Status board

| # | FE task | Status |
|---|---------|--------|
| FE-00 | Foundation | 🟨 (TanStack Query/Table, React Hook Form + Zod, Zustand, Recharts, Vitest + Testing Library, openapi-typescript all added 2026-10-17 — see Decisions) |
| FE-01 | Auth & shell | 🟨 (email/pw + staff phone/pw login wired to real JWT login; permission-matrix nav & route guards driven by GET /auth/me/ permissions; async session-purge coordinator (F7) added 2026-10-17; BFF proxy + httpOnly-cookie auth built 2026-10-19 (§3.1); optional email-code login in the Owner and Staff views 2026-10-21; `/signup` → check-email → `/verify-email` (token in the URL fragment, never signs in) + resend on `EMAIL_NOT_VERIFIED` login + profile verification badge 2026-10-21; real `/forgot-password` + `/reset-password` (also the staff-invite set-password page) and a real Settings → change-password (re-issues the session cookies) 2026-10-21; phone OTP still future work) |
| FE-02 | Property setup | 🟨 (Add Property form wired to real API incl. images; Module 18 Features page + optional features section wired to real API; `/properties/[id]` is now the D2 bed-grid overview — see Decisions; the floor/room/bed *builder* forms still predate this round) |
| FE-03 | Property settings | ⬜ (the `/properties/[id]/settings` page is still the mock `PropertySettingsForm`; Settings no longer links real properties to it, 2026-10-21) |
| FE-04 | Residents | 🟨 (list filters (property/status/search) now server-side; D6 finance card replaces the old dead-field Financials tab; document upload/blacklist warning still from the earlier round) |
| FE-05 | Admissions | ⬜ |
| FE-06 | Allocations | ⬜ |
| FE-D1 | Occupancy dashboard | ✅ (analytics/summary/, per-section state rule) |
| FE-07 | Discounts | ✅ (report tab on /billing: property/resident/reason/type filters, create, end via valid_until) |
| FE-08 | Billing | 🟨 (invoice list/detail/line-items/issue/draft-edit/delete, bulk/single generate; invoice PDF and waive-with-note have no backend endpoint yet) |
| FE-09 | Payments | ✅ (idempotent record-payment dialog, delete-as-reversal, receipt JSON/PDF/share, cash movements; refunds/credits out of scope per owner decision 2026-10-16) |
| FE-10 | Deposits & exit | ⬜ |
| FE-D2 | Financial dashboard | ✅ (analytics/summary/, same per-section rule as FE-D1) |
| FE-11 | Complaints | ⬜ |
| FE-12 | Visitors | 🟨 (Visitors log & check-in/out page shipped in (owner)/visitors, gated by manage_visitors; resident requests/approvals V2) |
| FE-13 | Subscription + Super Admin | 🟨 (Owner plan screen shipped in Settings → Plan & Billing, gated by manage_subscription: trial/status, bed usage, plan comparison, switch + Razorpay Checkout; billing history, suspension lock screen and the Super Admin portal not started) |
| FE-14 | Notifications | 🟨 (Web Push built 2026-10-19: opt-in on More, foreground toast, tap deep links, unsubscribe on logout; notification preferences UI not started) |
| FE-15 | Audit logs | ⬜ |
| FE-16 | Activity timeline | ⬜ |
| FE-17 | Export | 🟨 (residents/payments/outstanding-dues/occupancy/expenses/pnl, csv/xlsx/pdf, each gated on its own endpoint permission; the PRD's "async job status" is obsolete — exports are synchronous) |
| FE-20 | Expenses (Module 20) | ✅ (month nav, category chips from expenses/summary/, add/edit sheet with idempotent create + attachment upload, category manager) |
| FE-21 | Reports / Analytics (Module 21) | ✅ (/reports: Overview/Collections/Occupancy/Exports tabs, 6-month trend chart) |
| FE-M | Public marketing site (§12) | 🟨 (all routes, en + te, per-surface availability matrix, QR/app page, public plans + support contacts, SEO files built 2026-10-18; **launch blocked** on company identity env vars, real support contacts configured in Super Admin, legal review, the deploy gate and signup (CTA stays "Request early access" until `SIGNUP_ENABLED`)) |
| FE-P1 | PWA hardening | 🟨 (manifest, Serwist worker, read-only offline, update toast, install UX, iOS polish built 2026-10-19; **still open:** Lighthouse CI gate, verification on a real iPhone, Razorpay Checkout return-to-app check in standalone, iOS splash images; Android-style phone look built 2026-10-20 for Dashboard, Residents, Properties and the new Vacancies screen — other screens follow) |
| FE-R1 | Resident portal | ⬜ |

---

## 8. Testing & quality gates

- **Unit/component** (Vitest + RTL): every business-rule rendering — money formatting from
  string decimals, status badge mapping, line-item iteration, LimitGate on 409.
- **E2E** (Playwright): one happy path per phase (signup→property→admission→check-in;
  invoice→partial payment→receipt; notice→vacate→refund) + a role test proving a
  Receptionist cannot reach billing routes and a Manager cannot see unassigned properties.
- **PWA** (Lighthouse CI): installability, offline fallback, performance budget
  (dashboard LCP < 2.5s on mid-range Android — primary user device).
- **i18n lint**: build fails on literal JSX strings or missing message keys.
- **Contract safety**: CI regenerates types from the backend OpenAPI schema; type errors
  on drift fail the build.

---

## 9. Non-functional targets

- Mobile-first responsive layouts (owners run PGs from phones); desktop for reports.
- Code-split per route group; resident portal bundle kept minimal (it's the PWA target).
- Accessibility: WCAG AA on forms and tables (keyboard nav, labels, contrast).

---

## 10. Backend prerequisites this plan adds

Small additions to note in the relevant module specs when built:
1. **drf-spectacular** OpenAPI schema (module 01) — needed for type codegen and MSW mocks.
2. **Permission matrix / allowed-actions in serializers** (module 01 onward) — invariant F8.
3. Machine-readable error codes (e.g., `PLAN_LIMIT_REACHED`, `SUBSCRIPTION_SUSPENDED`,
   `BLACKLIST_MATCH`) on 4xx responses (module 01/13) — invariant F4 and suspension UX.
4. Document uploads: uploads go browser→BFF→Django→GCS (never browser→bucket); files come back as 5-minute signed GCS URLs (docs/deployment.md). No presigned-upload endpoints.
5. ~~V2: `push_subscriptions` endpoint for Web Push (module 14).~~ Done —
   see `docs/modules/14-notifications.md` (2026-09-17).

---

## 11. Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Web frontend exists (reverses old CLAUDE.md rule) | Next.js + PWA | Owner decision 2026-07-02; matches PRD §12 tech stack |
| Next.js version | 15 (App Router), not PRD's 14 | 14 was current when PRD was drafted; no reason to start a new app on an old major |
| i18n library | next-intl, not PRD's next-i18next | next-i18next targets the Pages Router; next-intl is the maintained App Router standard. PRD i18n requirements (per-module JSON, externalised strings, Noto fonts) are met identically |
| PWA tooling | Serwist, not next-pwa | next-pwa is unmaintained; Serwist is its actively maintained successor on Workbox |
| Token storage | httpOnly cookies via BFF proxy | Keeps JWTs out of JS (XSS), avoids CORS, lets the service worker treat API as same-origin |
| Locale in URL | No — cookie/profile based (still true after 2026-10-18; see §12 for the marketing consequence) | Authed dashboard, no SEO need; PRD stores `language_code` per user. The public site stays cookie-based too, so **English is the only indexed language**; `/te/...` URLs would reverse this row and need owner sign-off |
| Offline writes | None in MVP | Money mutations must not replay/conflict; PRD has no offline requirement. Read-only offline + V2 Background Sync for non-money modules |
| Mobile app | PWA covers residents for MVP; Flutter next (Android + iOS together) | PRD lists mobile apps as V2; PWA delivers "mobile-first resident experience" (PRD §2) now |
| Mobile client build order (2026-07-05) | Web/PWA -> Android -> iOS, all as clients of one Django API | Owner confirmed sequencing; avoids building two native apps in parallel and confirms the API needs no per-client redesign (§3.1a) |
| Mobile client tech (2026-09-17) | Flutter (Dart), one codebase for Android + iOS — supersedes the 2026-07-05 native-Android-then-native-iOS plan (Kotlin/Compose, Swift/SwiftUI) | Owner decision; keeps the "one Django API, no per-client redesign" principle from the row above (§3.1a) — only the client implementation technology changes, not the sequencing or API contract |
| Auth for Add Property (2026-07-05) | Temporary direct-to-Django client (`lib/api.ts`): real login, JWT in `localStorage`, dev-only CORS — not the §3.1 BFF proxy | The BFF proxy (FE-01) didn't exist yet and nothing in the app called the real backend; owner approved a minimal unblock to get the Add Property form (module 02) working now rather than building the full proxy first. **Resolved 2026-10-19:** replaced by the §3.1 BFF proxy (see the "BFF proxy built" row below); see `docs/modules/02-property-hierarchy.md` Decisions. |
| Receptionist portal consolidation (2026-10-11) | Single `(owner)` shell for Owner, Manager, and Receptionist — no separate `(reception)` portal group | Keeps the layout, navigation, and mobile UX unified across all staff roles. What each role can view and mutate is governed purely by `PERMISSION_MATRIX` codes from `/auth/me/`, rather than maintaining multiple shell layouts. |
| Per-staff module access (2026-10-12) | `(owner)/staff/[id]` Team Management screen: module toggles + level picker + PG access; nav, page guards and redirects are all driven by `/auth/me/` permissions (`view_dashboard`, `view_finance`, `view_resident_profile`, `view_property_features`…); `RequirePermission` falls back to the first allowed route (`firstAllowedRoute`), never a role landing page; permissions refresh on tab focus (throttled) and after any 403 | Owner request superseding the fixed per-role matrix (Module 01 `[DECISION 2026-10-12]`); access is per person, so no screen can be assumed reachable by role (F8). No frontend test runner exists yet — behavior is verified by the manual script in the change's plan |
| Permission-driven nav & route guards (2026-10-11) | Client-side session check (`useSession()`, `useSyncExternalStore` cached + revalidated via `GET /auth/me/` once per load) with `<RequirePermission>` and `<PermissionGate>` | Replaces role-name-based navigation. Acts as a client-side UX guard to hide disallowed buttons and prevent 403 errors; explicitly **not** the §3.1 BFF/httpOnly-cookie design (which remains future work). True authorization boundary remains server-side `require_permission()` checks. |
| Portal login boundaries (2026-10-11) | Upfront Owner / Staff choice; strict role validation; Super Admin and Resident logins explicitly rejected | Prevents redirection loops or dead-ends for roles with no portal UI in this web app. Owner login requires `owner` role; Staff login requires `manager` or `receptionist`. Stray `super_admin` or `resident` credentials show a clear localized error. |
| UX roadmap web client (2026-10-17) | §2's named stack adopted in full: TanStack Query + Table, React Hook Form + Zod, Zustand, Recharts, Vitest + Testing Library, `openapi-typescript` | None of these were installed before this round (the app ran on plain `useEffect`+`useState`+`apiFetch` with no test runner). `/billing` (replacing the mock `/financials`), `/expenses`, `/reports`, and the `/properties/[id]` bed-grid overview are the first screens built against this stack. |
| API types: generated schema checked in, hand-written types kept (2026-10-17) | `npm run gen:api` → `src/lib/api-schema.d.ts` (committed, regenerate on backend schema changes) exists and is wired up, but every feature built in this round (`lib/api.ts`) still hand-writes its interfaces, matching the rest of the file | §2 says "no hand-written response interfaces" — this is a **partial reversal**, not full compliance: hand-written types shipped faster for ~15 new endpoints and matched the file's existing 100%-hand-written convention, so mixing the two styles mid-file seemed worse than being consistent. The schema is real and available; migrating `lib/api.ts` to alias from it is left as follow-up work, not attempted here. |
| Bed transitions read from the backend (2026-10-17) | `allowed_transitions` (added to `BedSerializer` and the D2 layout) is the only source the UI offers status-change actions from — no client-side copy of the D9 transition table | Invariant F8 ("the frontend never invents transitions") can't be satisfied by a client-side table that can silently drift from what `PATCH /beds/{id}/` actually accepts; this was a small, additive backend change (no migration) specifically to give the web client (and any future client) a servable source of truth. |
| `/financials` replaced, not kept alongside `/billing` (2026-10-17) | The route now redirects to `/billing`; `features/financials/FinancialsDashboard.tsx` (a hardcoded 2024 mock, never wired to the API) was deleted | It was pure placeholder UI with no real data path — keeping it as a second, dead billing screen alongside the new real one would only confuse the route map. |
| Session purge made async + awaited everywhere (2026-10-17) | `clearSession()` is now `async`, clearing tokens/permissions synchronously first, then awaiting the query cache clear, every Zustand store reset, and Cache Storage/IndexedDB sweeps through `Promise.allSettled`; `login()`/`loginPhone()` await any purge already in flight | Invariant F7 needs more than `localStorage.removeItem` once TanStack Query and Zustand hold cross-request state — a purge that isn't awaited (or that one failing step could abort) risks a new session briefly rendering with the old tenant's cached data. |
| Account deletion UI (2026-10-23) | `(owner)/profile` danger-zone card; `app/account/deletion-pending` as its own top-level route (no `(owner)` layout, whose nav/queries are what a locked account's 403s hit); public `(marketing)/delete-account` for Google Play's Delete account URL; a dedicated BFF handler `app/api/auth/request-account-deletion` because the POST returns a token pair (so `isTokenIssuingPath` is now method-aware: POST refused by the generic proxy, GET/DELETE forwarded); `apiFetch` treats a 403 with a deletion code as a locked-but-live session (no `clearSession`, redirect once, never loop) | Additive to §3.1 (tokens still never reach page JS) and the route map; backend spec in modules/22-account-deletion.md |
| Discount report columns moved to the backend (2026-10-17) | `DiscountSerializer` gained `ResidentContextMixin` (resident_name/property/property_name/room_number/bed_number) and a `?property=` filter, matching invoices and payments, instead of the web client joining residents client-side | Keeps one definition of "who/where" for every finance list, and avoids an N+1 client-side join the web client would otherwise need for the Discounts tab on `/billing`. |
| Reports access vs. export access are two different checks (2026-10-17) | The `/reports` nav item and route need `view_reports` (`view_dashboard`-only users get the same figures inline on `/dashboard` instead); each export button on the Exports tab, and the context-export buttons on `/billing`/`/residents`/`/expenses`, are gated only by that export's own endpoint permission — `view_reports` is never required to export | Matches the backend exactly: `ResidentExportView`/`PaymentExportView`/etc. check `view_resident_profile`/`view_finance`/etc., not `view_reports`. A Manager with Finance access but no Reports module access can still export payments from `/billing`. |
| Dashboard revenue delta dropped for now (2026-10-17) | `FinancialsSummary.revenueDelta` is optional and the dashboard doesn't populate it | Computing "vs last month" needs a second `analytics/summary/` call (last month's `cash_collected`); the old client-side version summed raw payment lists instead (an invariant F1 violation this round removed). Left as follow-up rather than adding a second round-trip to this pass. |
| iOS PWA as the staff app on iPhone (2026-10-19) | The installable PWA serves Owner/Manager/Receptionist on iPhone until the Flutter iOS build ships; Android uses the Flutter app. Residents have no login, so no resident portal is involved | Owner request: Android is in progress, there is no iOS build, and iPhone owners need the signed-in app now (not the public marketing site). Supersedes "PWA covers the resident experience" for the interim. |
| BFF proxy built, token storage moved out of JS (2026-10-19) | JWTs live only in httpOnly cookies (`pg_access`/`pg_refresh`, path `/api`); `lib/api.ts` is same-origin with no token code; `NEXT_PUBLIC_API_URL` is replaced by server-only `INTERNAL_API_URL` | Owner decision: build the BFF before real iPhone users. Details and deployment requirements in §3.1. |
| Web Push pulled forward from V2 (2026-10-19) | Built now, following `docs/push-notifications-integration.md` §6 and reusing the Serwist worker | Owner decision, alongside the iOS PWA. Push is unavailable in dev (the worker is production-only). |
| Offline is read-only; query and mutation network modes (2026-10-19) | Queries use `networkMode: "offlineFirst"` (so the worker's cached GETs are reachable); mutations use `"always"` | TanStack's default `"online"` *pauses* a mutation made offline and *replays* it on reconnect — an implicit offline queue for payments, contradicting "Offline writes: none in MVP". With `"always"` it fails fast instead. |
| Per-user API cache, precache kept across logout (2026-10-19) | Worker caches per `X-Cache-Scope`; logout deletes every cache except precache/`next-static`/`app-images` | The worker can't read httpOnly cookies, so the page supplies the scope. A missed purge (offline logout, crashed tab) then still cannot show user A's data to user B, and the app shell survives logout. Supersedes "all caches purged on logout" in §5.1's earlier wording. |
| `next build --webpack` (2026-10-19) | The production build uses webpack (dev already did) | `@serwist/next` is a webpack plugin and Next 16 builds with Turbopack by default. |
| iOS status bar style `default`, not `black-translucent` (2026-10-19) | `appleWebApp.statusBarStyle: "default"` | `black-translucent` draws white clock/battery over our light page background, which is unreadable; `default` also keeps content below the status bar so only the bottom safe area needs handling. |
| `/~offline` language and API cache age (2026-10-19) | The fallback page is cached in the language active when the worker installed; API reads stay usable offline for 5 minutes (`API_CACHE_MAX_AGE_SECONDS` in `sw.ts`) | The page is server-rendered from the locale cookie, so it cannot switch language offline. Five minutes is the §5.1 figure and errs toward not showing stale money screens; raising it is a one-line change if owners want longer offline reads. |
| Phone UI follows the Android (Material 3) look (2026-10-20) | Below `md` only: Material tokens (`--color-m3-*`, sampled from the Android screenshots) added beside — not replacing — the desktop tokens; Roboto on phones via `.phone-ui`; top app bar + property pill, tonal 5-tab bottom nav (Dashboard, Properties, Residents, Billing, More — explicit `MOBILE_NAV_ITEMS`, not a slice of the sidebar list), outlined cards, filter chips, extended FABs. Phone components live in `components/mobile/`; desktop components are untouched. Dashboard, Residents, Properties and the new Vacancies screen are reshaped; every other screen only inherits the shell | Owner request: iPhone users get this PWA instead of the Flutter app and it should feel like the same product. Deliberately not a global re-theme: desktop is unchanged and the other screens follow in later passes. UI-level only — no change to stack, auth, offline behaviour or build order. |
| Vacancies screen (2026-10-20) | `/vacancies`: vacant beds and residents on notice per property, built from `GET /properties/{id}/layout/` (no new API), one query per property (`useQueries`) so a failing property never blanks the others. Without `view_resident_profile` the layout hides residents, so the On Notice tile, pills and section are hidden — never shown as zero. "+ Admit" opens `/admissions?property=&bed=`; the wizard stays on step 1 and step 2 opens with that bed selected (`lib/admissionPreselect.ts`) | Matches the Android screen. Not in the bottom nav: reached from the dashboard shortcut. Room rate shown is the lower of the with-food / without-food rack rates (`compareMoney`), "from" when they differ; display only, billing still uses `contracted_rent`. |
| Dashboard sections follow the property selector (2026-10-20) | Complaints, admissions, residents and payments queries now carry the selected property (and it is in their query keys), not just the analytics summary. Needed a `property` filter on `GET /complaints/` and `GET /admissions/` (backend, additive) | The phone property pill would otherwise change occupancy but leave issues and activity showing every property. Fixes the same inconsistency on desktop. Phone "Today's Activity" only lists the device's local calendar day. |
| Phone layout plumbing (2026-10-20) | The offline banner publishes its measured height as `--banner-h` so the sticky top bar sits just below it; a mounted FAB publishes `--fab-stack` so the update toast stacks above it (nav → FAB → toast). `LAYOUT_ENTRY_PERMISSIONS` lives in `lib/layoutAccess.ts`, not `lib/permissions.ts` | The owner layout's content column is `min-w-0` so a sideways-scrolling row (dashboard shortcuts, chips) cannot widen the page. A server component importing a plain value from a client module (`permissions.ts`) gets a client reference, not the array — found on the Vacancies route. |
| Frontend image on Node 24 (2026-10-19) | `frontend/Dockerfile` is `node:24-alpine` (was `node:20-alpine`) | The Firebase SDK (`firebase` 12.x and 13.x both depend on `@firebase/app` 0.16) requires Node >= 24.12, so there is no Node-20-compatible release to pin to. Next 16 supports Node 24. `package-lock.json` was regenerated in a Linux container so `npm ci` sees the optional platform packages a Windows install omits. |


---

## 12. Public marketing site (pglive.in)

Added 2026-10-18 on owner request (domain `pglive.in`; brand **PGLive**; Android app "in review / coming soon").
It lives **inside this Next.js app** as the `(marketing)` route group — shared tokens, next-intl and deploy —
and deliberately deviates from §3.2 (which had `/` redirecting to login) and the old "no SEO need" stance.

### 12.1 Routes
`/` landing · `/features` (per-surface availability) · `/pricing` · `/app` (Android landing + QR target) ·
`/contact` · `/privacy` · `/terms` · app-wide 404. `robots.ts` / `sitemap.ts` / `opengraph-image` / root `icon.png` + `favicon.ico`.
The root layout sends `noindex` for everything; `(marketing)/layout.tsx` opts back in. `robots.txt` also
disallows the owner routes (keep `APP_PATHS` in `app/robots.ts` in step with `app/(owner)`).

### 12.2 Rendering & caching (decision: cookie locale, dynamic HTML, English indexed)
Locale comes from `cookies()` (`i18n/request.ts`), so every page is rendered per request. We accept that rather
than pretend: HTML is **not** CDN-cacheable; `proxy.ts` skips marketing paths only so anonymous visitors get no
`Set-Cookie`. Data is cached instead — `fetch(..., { next: { revalidate: 300 } })` for the two public API calls.
Telugu is a visitor convenience, not an SEO surface. Alternatives rejected for now: a separate English-only static
layout, and `/en` `/te` URL prefixes (best SEO/CDN, but reverses the §11 "Locale in URL" row).

### 12.3 Primary CTA
Login only serves existing accounts and signup is unbuilt (FE-01), so the CTA never points at `/login`.
`SIGNUP_ENABLED=false` (default): **"Request early access"** → WhatsApp (pre-filled) → email → `/contact`, from the
Super-Admin-managed contacts. `SIGNUP_ENABLED=true`: **"Start free trial"** → `/signup` (built 2026-10-21), and the
login page shows a "Start free trial" link. The flag is **discovery-only** (owner decision 2026-10-21): `/signup` and
the signup API stay reachable by URL while it is false, so early-access owners can be onboarded by sending the link.
Logic: `features/marketing/cta.ts`. The header shows **"Open dashboard"** instead of "Log in" only for a session
re-validated by `ensureFreshSession()` and only for roles that have a portal (owner/manager/receptionist).

### 12.3a Contact form (`/contact`)
A client form (`features/marketing/ContactForm.tsx`, react-hook-form + zod mirroring the backend serializer) posts to
`POST /api/v1/public/contact/` with `apiFetch(..., { skipAuth: true })`; the row is stored as a `ContactMessage` and read
in **Django admin → Core → Contact messages** (read-only content, audited "mark handled/new"; Module 01). No email is
sent. Marketing messages are not in the client provider, so the server component passes every string as a `labels`
prop. Spam controls: hidden honeypot (its input is not named `website`/`url`, which browsers autofill), server throttles
(5/h per IP, 3/h per email) with a translated 429 message, and a body-size cap.
**The browser posts straight to the API** so the real client IP is seen — in production this needs the CORS origin for
`https://pglive.in` (see §12.8 item 5); without it the form shows the translated "could not reach the server" message.

### 12.4 Public data (no baked-in values — invariant 10 / F4)
- Plans: `GET /api/v1/public/plans/` → `{currency, trial_days, updated_at, plans[]}` (Module 13).
- Contacts: `GET /api/v1/support/` (Module 01) — edited in Super Admin, no deploy.
- Fetched server-side from `INTERNAL_API_URL` (e.g. `http://backend:8000`; `localhost` inside the container is
  the frontend). 3 s timeout, Zod-validated, 5-min revalidate; failures are logged (`[marketing] GET … failed`) so a wrong
  `INTERNAL_API_URL` is visible. After changing compose env, **recreate** the container (`docker compose up -d --force-recreate frontend`);
  `restart` keeps the old environment. On failure: last validated response, else
  **"Pricing temporarily unavailable"** / "contact details are being set up". There is no static price fallback.

### 12.5 Truthful claims
`features/marketing/content/features.ts` is the single source for what is usable, per surface
(`ownerWeb`, `residentWeb`, `mobileApp`) with states `available | preview | comingSoon | notPlanned`; copy lives in
`messages/<locale>/marketing.json`. **Update it whenever a §7 status changes.** Tests forbid marking the Android app
or the resident web portal `available` until that is deliberately changed. App screens are labelled
"Concept preview", name their role, and say where that experience exists today.

### 12.6 Android app page (`/app`)
Permanent landing page, never a redirect. QR (`public/qr-app.svg`) encodes `https://pglive.in/app`, so it can be
printed before the Play listing exists. States (`APP_STATUS`): `comingSoon` (default; early-access "notify me")
and `live` (requires `PLAY_STORE_URL` on play.google.com, else it falls back to `comingSoon` and fails the launch
gate). Swap the text button for Google's official badge artwork when the listing is live.
Regenerate the QR with the `qrcode` npm package (v1.5.4, `QRCode.toString(url, { type: "svg", errorCorrectionLevel: "M", margin: 2 })`) in a scratch directory — it is intentionally not a project dependency. Scan-test the result before committing.

### 12.7 Configuration (server env, read at runtime)
| Variable | Meaning | Default |
|---|---|---|
| `SITE_URL` | canonical origin (https) | `https://pglive.in` |
| `SITE_ENV` | `production` or `staging` (staging: no launch gate, `robots.txt` disallows all) | `production` |
| `COMPANY_NAME`, `COMPANY_ADDRESS` | legal identity for footer / privacy / terms / JSON-LD | **required in production** |
| `APP_STATUS`, `PLAY_STORE_URL` | `comingSoon` \| `live`, and the store link | `comingSoon` |
| `SIGNUP_ENABLED` | flips the CTA to the trial and shows the login page's signup link (discovery only — `/signup` works regardless) | `false` |
| `INTERNAL_API_URL` | server-side Django origin (also used by the BFF proxy, §3.1) | falls back to `NEXT_PUBLIC_API_URL`, then `http://localhost:8000` |

### 12.8 Launch gates
1. **Config gate:** `next build` (`next.config.ts`) and server start (`instrumentation.ts`) fail in production while
   company identity is missing or `APP_STATUS=live` lacks a valid Play URL. Staging builds set `SITE_ENV=staging`.
2. **Contacts:** a Super Admin must set support email/phone/WhatsApp (`PlatformConfig`) — otherwise `/contact`
   shows "being set up" and the CTA falls back to `/contact`.
3. **Legal:** Privacy/Terms are drafts (banner shown) pending legal review; Telugu falls back to English for them.
4. **Security headers:** baseline (nosniff, referrer, frame, permissions) is on. **CSP is not enabled** — inventory
   Razorpay, Google Maps, Firebase, API/image/font origins, run `Content-Security-Policy-Report-Only`, then enforce
   only after the owner app is verified under it.
5. **Deployability (nothing exists yet):** production Dockerfile (`output: "standalone"`, not `npm run dev`),
   TLS + apex↔`www` redirect, Django `ALLOWED_HOSTS` (must include the host the BFF proxy calls, §3.1) / `CSRF_TRUSTED_ORIGINS`, and a separate API host (**no CORS is needed for the contact form:** since the BFF landed it posts same-origin through `/api`), a trusted-proxy policy so client IPs (throttling, stored IP) are real, health checks, rollback, cache headers for static assets.
6. **Translations:** Telugu copy needs native-speaker review; legal text needs a Telugu translation or an explicit
   "English governs" statement.
7. **Brand:** resolved 2026-10-20 — the signed-in app is now **PGLive** too (`messages/*/common.json`, root metadata,
   manifest, auth and PWA strings), matching the marketing site. (The Android app's header still says "PG Mate".)

**Production pass 2026-10-21 (error pages, no fabricated data).** `app/error.tsx` and `app/global-error.tsx` replace Next's default crash screen. Both render the shared `components/shared/ErrorView`; `global-error` replaces the root layout, so it has its own `<html>/<body>`, no providers, and reads the five `messages/<locale>/errors.json` catalogs statically (`lib/errorCopy.ts`, locale from the `NEXT_LOCALE` cookie, then the browser language). `lib/api.ts` no longer falls back to a built-in feature catalog, an empty list or an invented custom feature when a request fails, and the `skyline`/`sunset` demo ids are gone: a non-UUID id is a 404 and nothing is fetched. Settings → Property Setup lists the tenant's real properties; the fake "Save portal" form, its other-brand defaults and the starter/mock files were removed.

**Google Maps picker (2026-10-21).** `PropertyMapPicker` moved off the legacy `places.Autocomplete` and `google.maps.Marker` to `PlaceAutocompleteElement` (Places API New) and `AdvancedMarkerElement` (needs a Map ID), loaded through `importLibrary` (`lib/googleMaps.ts`). The key is only the build-time `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY`: the "paste your key" box that saved it to `localStorage` is gone, and without a key the picker says "Map unavailable" while manual coordinates still work. Its strings are i18n'd and `alert()` is replaced by inline messages. **Verify with the real key on first run** (search selection event name, Map ID rendering): the unit tests use a fake Google object.
