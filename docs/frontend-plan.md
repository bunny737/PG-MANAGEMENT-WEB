# Frontend Plan — Next.js Web App + PWA

> Status: Approved by owner on 2026-07-02 (supersedes the earlier "backend only" rule in CLAUDE.md)
> Source of truth for all frontend work. Read alongside `pg_hostel_management_prd_v2.md` and `modules/README.md`.

---

## 1. Scope

A single Next.js web application serving all five roles (Super Admin, Owner, Manager,
Receptionist, Resident), installable as a PWA on Android/iOS/desktop. This is the primary
UI for MVP. Native Android (Kotlin) remains a later-phase companion app — the PWA covers
the mobile-first resident experience until then.

The frontend is a pure API client. All business rules (billing math, status transitions,
plan limits, penalties) live in the Django backend. The frontend renders, validates input
shape, and never re-implements money logic.

---

## 2. Stack

| Concern | Choice | Notes |
|---------|--------|-------|
| Framework | Next.js 15 (App Router) + React 19 + TypeScript (strict) | PRD says "Next.js 14" — written June 2026; scaffold on current stable 15.x |
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

## 3. Architecture

### 3.1 API integration — BFF proxy with httpOnly cookies

- Browser never sees JWTs. Next.js Route Handlers under `app/api/[...path]/route.ts`
  proxy every call to Django (`/api/v1/...`).
- Access token (15 min) + refresh token (7 days) stored in `httpOnly; Secure; SameSite=Lax`
  cookies set by the proxy. Proxy transparently refreshes on 401-expired and retries once.
- Refresh failure, account suspension (`403 SUBSCRIPTION_SUSPENDED`), or force-logout →
  proxy clears cookies, client redirects to `/login` with a translated reason banner.
- Next.js `middleware.ts` guards route groups by role claim (decoded server-side only);
  the API remains the real authority — middleware is UX, not security.
- Same-origin API calls mean no CORS config and the service worker can apply cache
  strategies uniformly.

### 3.2 Route map (App Router route groups)

```
app/
├── (auth)/                     login, signup (tenant onboarding + 60-day trial),
│                               verify-email, otp, forgot-password, reset-password
├── (owner)/                    Owner + Manager portal (nav filtered by permission matrix)
│   ├── dashboard/              occupancy + financial dashboards
│   ├── properties/[id]/        floors / rooms / beds setup, bed grid
│   │   └── settings/           Module 2B: transfer rent timing, penalty config
│   ├── residents/[id]/         profile, documents, timeline, discounts
│   ├── admissions/             pipeline: Inquiry → Visit → Reserved → Admission → Check-in
│   ├── allocations/            bed board, temporary-allocation list, transfers
│   ├── billing/
│   │   ├── invoices/[id]/      line-item detail, PDF download
│   │   └── payments/           record payment, receipts, outstanding dues
│   ├── deposits/               notice period, vacating wizard, absconded flow
│   ├── complaints/             status board, comment threads
│   ├── visitors/               log + history
│   ├── staff/                  Owner only: Manager/Receptionist accounts + property assignment
│   ├── reports/                exports (CSV/Excel/PDF)
│   └── subscription/           Owner only: plan usage, upgrade via Razorpay, billing history
├── (reception)/                Receptionist portal: visitors + read-only resident lookup
├── (resident)/                 Resident portal (primary PWA install target)
│   ├── home/  invoices/  receipts/  complaints/  visitors/  notices/  profile/
├── (superadmin)/               tenants, plan-limit config, platform metrics, overrides
├── api/[...path]/              BFF proxy to Django
├── manifest.ts                 PWA manifest
├── ~offline/                   offline fallback page
└── sw.ts                       Serwist service worker
```

Owner and Manager share the `(owner)` portal: navigation and actions are filtered by the
permission matrix (PRD §6) fetched from the backend at session start — never inferred
client-side from role names. Managers see a **property switcher** scoped to assigned
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
    rule blocks literal JSX text. Language switcher shipped in MVP, English-only active.
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
F8. **The frontend never invents transitions.** Action buttons (vacate, abscond, blacklist,
    waive penalty) appear only when the API's serialized `allowed_actions` / permission
    matrix says so.

---

## 5. PWA plan

### 5.1 Baseline (MVP)

- **Manifest** (`app/manifest.ts`): standalone display, portrait, theme/background colors,
  192/512 icons + maskable variants, `start_url: /` (server redirects to role home).
- **Service worker** via Serwist:
  - Precache: app shell, fonts, offline fallback page.
  - `CacheFirst` — hashed Next.js static chunks, fonts.
  - `StaleWhileRevalidate` — images, icons.
  - `NetworkFirst` (3s timeout, 5-min max age) — API **GET**s only, so recently viewed
    dashboards/lists/invoices remain readable offline.
  - **Mutations are never cached or queued in MVP.** Money-touching writes (payments,
    invoices, deductions) must not risk replay/conflict. Offline = read-only, with a
    persistent `OfflineBanner`. Background Sync queue is a V2 item, non-money modules first.
- **Install UX**: capture `beforeinstallprompt` for a custom "Install app" button
  (shown prominently in the resident portal); iOS gets an instructions sheet
  (`apple-touch-icon` + splash configured).
- **Cache hygiene** (invariant F7): runtime cache names include the session's tenant+user
  hash; all caches purged on logout. Auth/proxy responses are `Cache-Control: no-store`.
- **CI gate**: Lighthouse PWA installability + performance budget on the resident portal
  and owner dashboard.

### 5.2 V2

- Web Push notifications (invoice issued, payment receipt, complaint updates) — aligns
  with PRD Module 18 V2. Requires a `push_subscriptions` endpoint backend-side.
- Background Sync for non-money mutations (complaints, visitor requests).
- Periodic background refresh of the resident's own invoice list.

---

## 6. i18n plan

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
| FE-04 Residents | 04 | list + status filters, profile, document upload (S3 presigned), blacklist warning on re-registration |
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
| FE-17 Export | 17 | CSV/Excel/PDF export buttons with async job status |
| FE-P1 PWA hardening | — | offline fallback polish, install prompts, cache purge audit, Lighthouse pass |
| FE-R1 Resident portal | 04, 08, 09, 11, 12 | resident-facing home, invoices, receipts, complaints, visitor requests, notices |

### Status board

| # | FE task | Status |
|---|---------|--------|
| FE-00 | Foundation | ⬜ |
| FE-01 | Auth & shell | ⬜ |
| FE-02 | Property setup | ⬜ |
| FE-03 | Property settings | ⬜ |
| FE-04 | Residents | ⬜ |
| FE-05 | Admissions | ⬜ |
| FE-06 | Allocations | ⬜ |
| FE-D1 | Occupancy dashboard | ⬜ |
| FE-07 | Discounts | ⬜ |
| FE-08 | Billing | ⬜ |
| FE-09 | Payments | ⬜ |
| FE-10 | Deposits & exit | ⬜ |
| FE-D2 | Financial dashboard | ⬜ |
| FE-11 | Complaints | ⬜ |
| FE-12 | Visitors | ⬜ |
| FE-13 | Subscription + Super Admin | ⬜ |
| FE-14 | Notifications | ⬜ |
| FE-15 | Audit logs | ⬜ |
| FE-16 | Activity timeline | ⬜ |
| FE-17 | Export | ⬜ |
| FE-P1 | PWA hardening | ⬜ |
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
4. S3 presigned upload endpoints (module 04) — document uploads go browser→S3 direct.
5. V2: `push_subscriptions` endpoint for Web Push (module 14).

---

## 11. Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Web frontend exists (reverses old CLAUDE.md rule) | Next.js + PWA | Owner decision 2026-07-02; matches PRD §12 tech stack |
| Next.js version | 15 (App Router), not PRD's 14 | 14 was current when PRD was drafted; no reason to start a new app on an old major |
| i18n library | next-intl, not PRD's next-i18next | next-i18next targets the Pages Router; next-intl is the maintained App Router standard. PRD i18n requirements (per-module JSON, externalised strings, Noto fonts) are met identically |
| PWA tooling | Serwist, not next-pwa | next-pwa is unmaintained; Serwist is its actively maintained successor on Workbox |
| Token storage | httpOnly cookies via BFF proxy | Keeps JWTs out of JS (XSS), avoids CORS, lets the service worker treat API as same-origin |
| Locale in URL | No — cookie/profile based | Authed dashboard, no SEO need; PRD stores `language_code` per user |
| Offline writes | None in MVP | Money mutations must not replay/conflict; PRD has no offline requirement. Read-only offline + V2 Background Sync for non-money modules |
| Mobile app | PWA covers residents for MVP; native Android later | PRD lists mobile apps as V2; PWA delivers "mobile-first resident experience" (PRD §2) now |
