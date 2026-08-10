# Frontend i18n implementation plan

Detailed build plan for CLAUDE.md invariant 7 (no hardcoded UI strings) and
frontend-plan.md invariant F2. Expands `frontend-plan.md` §6 — that section states
the *what*; this document is the *how*, in dependency order, with acceptance
criteria per phase.

Status: **not started** (see §2). Owner of this doc: whoever picks up FE-00 i18n.

---

## 1. Scope

In scope:
- next-intl foundation in the Next.js app (provider, catalogs, locale resolution).
- Locale round-trip: user profile `language_code` ↔ cookie ↔ `<html lang>` ↔
  `Accept-Language` on API calls.
- Extraction of the ~40 existing components' literal strings into module catalogs.
- Language switcher: per-user (profile) and tenant default (Owner-only).
- Lint + CI enforcement so new literal strings cannot land.
- Font coverage for Indic scripts.

Out of scope (already built or deliberately deferred):
- Backend `gettext` plumbing, `translation.override()` in emails/Celery, and the
  per-user/per-tenant language columns — **already done**, see §2.
- Actual `hi`/`te`/`ta`/`ml` translations. MVP ships English-complete with the
  other four selectable-but-disabled. V2 = `hi`, `te`; V3 = `ta`, `ml`
  (PRD i18n table; `backend/config/settings/base.py:66-77`).
- Server-rendered PDF invoices/receipts — backend renders them in the user's
  language, the frontend only downloads. No client-side document generation.

---

## 2. Current state (audited 2026-08-10)

### Backend — essentially complete

| Capability | Where | State |
|---|---|---|
| `USE_I18N`, 5 `LANGUAGES`, `LOCALE_PATHS` | `backend/config/settings/base.py:66-78` | ✅ |
| `LocaleMiddleware` installed | `backend/config/settings/base.py:40` | ✅ |
| `Tenant.default_language` | `backend/apps/accounts/models.py:28` | ✅ |
| `User.language_code` | `backend/apps/accounts/models.py:81` | ✅ |
| JWT carries `language` claim | `backend/apps/accounts/serializers.py:148` | ✅ |
| `GET /auth/me/` returns `language_code` | `MeSerializer`, `serializers.py:262` | ✅ |
| `PATCH /auth/me/` accepts `language_code` | `MeUpdateSerializer`, `serializers.py:273` | ✅ |
| Signup seeds tenant default from Owner's pick | `serializers.py:80` | ✅ |
| Staff invite inherits tenant default | `serializers.py:330` | ✅ |
| Emails translated per recipient | `apps/accounts/emails.py:17` | ✅ |
| Notifications translated (user → tenant fallback) | `apps/notifications/tasks.py:77-78` | ✅ |
| `en` message catalog | `backend/locale/en/LC_MESSAGES/django.po` | ✅ |
| OpenAPI shares one `LanguageEnum` | `base.py:127` | ✅ |
| Test: language preference is per-user and editable | `apps/accounts/tests/test_me.py:35-43` | ✅ |

Two backend gaps, both small — see B1/B2 in §4.

### Frontend — nothing implemented

| Expected | Actual |
|---|---|
| `next-intl` dependency | **absent** from `frontend/package.json` |
| `src/messages/<locale>/<module>.json` | **absent** |
| `NextIntlClientProvider` / `i18n/request.ts` | **absent** |
| `src/middleware.ts` for locale | **absent** |
| `<html lang>` reflects locale | hardcoded `"en"`, `src/app/layout.tsx:48` |
| `eslint-plugin-i18next` blocking literal JSX | **absent**, `frontend/eslint.config.mjs` is stock `eslint-config-next` |
| Every user-facing string via `t()` | **zero** — all ~40 components use literal JSX |
| `language_code` on the API client's user type | **absent**, `CurrentUser` at `src/lib/api.ts:620-627` |
| `PATCH /auth/me/` wrapper | **absent** — `api.ts` has `getCurrentUser` only |
| Per-user language picker in profile settings | **absent** from `src/features/profile/UserProfile.tsx` |
| Tenant-default language picker | present but **fake** — `GlobalSettings.tsx:79-86` fakes a save with `setTimeout` |
| Language registry | `src/lib/constants/languages.ts` — new, untracked, hand-maintained duplicate of the backend enum |

Net: the Settings screen *looks* like i18n exists. Nothing behind it works, and the
component rendering that language picker is itself ~120 hardcoded English strings.

---

## 3. Target architecture

```
frontend/src/
├── i18n/
│   ├── config.ts        LOCALES registry (code, native name, status, script) — single source
│   ├── request.ts       next-intl getRequestConfig: resolve locale, merge module catalogs
│   └── locale.ts        readLocale()/writeLocale() cookie helpers (server + client)
├── messages/
│   ├── en/  common.json auth.json properties.json residents.json admissions.json
│   │        billing.json payments.json complaints.json settings.json status.json
│   ├── hi/  (V2 — files only, zero code)
│   └── te/ ta/ ml/
└── middleware.ts        seeds NEXT_LOCALE cookie when missing
```

Key mechanics:

1. **No locale URL prefix.** Cookie-based (`NEXT_LOCALE`), per frontend-plan
   Decisions §11 — this is an authed dashboard, SEO is irrelevant, and a prefix
   would churn every route in the app.
2. **Durable store is the user profile; cookie is the read path.** `language_code`
   from `/auth/me/` is authoritative. It is written to the cookie at login and on
   every profile change. SSR reads the cookie, never the API, so rendering never
   blocks on a network call. Cookie missing → tenant `default_language` from
   `/auth/me/` → `en`.
3. **Catalogs are per module, merged into namespaces.** `messages/en/billing.json`
   becomes the `billing` namespace, so `useTranslations('billing.invoice')` →
   `t('title')`. Keeps frontend-plan §3.3's file layout while giving next-intl the
   single object it wants.
4. **Formatting locale ≠ UI locale.** The product is India-only: numbers, currency
   and dates always format as `<code>-IN` (`en-IN`, `hi-IN`, …) so lakh/crore
   grouping and `₹` are correct regardless of UI language. This preserves
   invariant F1 — money stays a string from the API and is only ever *formatted*,
   never computed.
5. **API errors are translated by the backend.** The client sends
   `Accept-Language: <locale>` on every request; Django's `LocaleMiddleware` picks
   it up and DRF validation messages come back translated. **Important:** the
   middleware cannot read `request.user.language_code` — it runs before DRF
   authenticates the JWT, so the user is anonymous at that point. The header is
   the only synchronous lever. (Async paths already resolve the user's language
   correctly via `translation.override()`.)

---

## 4. Decisions and gaps to settle first

| # | Question | Decision |
|---|---|---|
| D1 | Where does the language registry live? | `src/i18n/config.ts`, generated-by-hand but **asserted against the OpenAPI `LanguageEnum` in a unit test** so backend/frontend drift fails CI. Fold the untracked `src/lib/constants/languages.ts` into it and delete that file. |
| D2 | Are non-`en` locales selectable in MVP? | Yes, shown with a "Coming soon" suffix and `disabled` — matches F2 ("language switcher shipped in MVP, English-only active") and what `languages.ts` already encodes. A disabled option cannot be submitted, so no half-translated UI can be reached. |
| D3 | Big-bang extraction or incremental? | **Incremental, by module.** ~40 components is too large a single diff to review safely. Lint rule lands as `warn` globally, flipped to `error` per directory as each module is converted (§5, P3). |
| D4 | Does the tenant default belong in Settings or Profile? | Both, distinctly. Profile = *my* language (PRD: primary mechanism, any user). Settings → Account & Security = *tenant default for new accounts* (PRD: Owner-only override). Today only the second exists and it is mislabelled "Default Interface Language" as though it changed the current user's UI. |
| B1 | Backend: can a tenant's `default_language` be updated? | **No — gap.** `TenantSerializer` is read-only (`serializers.py:250-251`). Needs a writable Owner-only path before the Settings picker can work. |
| B2 | Backend: is `Accept-Language` honoured on API responses? | Mechanically yes (`LocaleMiddleware`), but untested and no client sends it. Needs one test asserting a validation error changes language with the header. |

---

## 5. Phased build

Each phase is independently shippable and leaves the app working.

### P0 — Verify the toolchain (blocking, do before writing any code)

- `frontend/AGENTS.md` rule: read `node_modules/next/dist/docs/` for the App
  Router i18n + `middleware` + `cookies()` guides **inside the container**
  (`docker compose exec frontend ...`) — `node_modules` is not on the host, and
  this is Next **16**, where APIs may differ from what you remember.
- Confirm the installed `next-intl` major supports Next 16 App Router and note
  the version in the Decisions table. If it does not, stop and raise it — the
  library choice is a frontend-plan-level decision (§ "When to stop and ask").

**Done when:** version compatibility is confirmed in writing.

### P1 — Foundation

Files: `package.json`, `next.config.ts`, `src/i18n/{config,request,locale}.ts`,
`src/messages/en/common.json`, `src/app/layout.tsx`.

- Add `next-intl`; wrap `next.config.ts` with its plugin.
- `src/i18n/config.ts`: `LOCALES` registry + `DEFAULT_LOCALE = 'en'` +
  `isActiveLocale()`. Port the five entries from `lib/constants/languages.ts`
  (status values there — `en` active, `hi`/`te` V2, `ta`/`ml` V3 — already match
  `base.py:66-67`; keep them).
- `src/i18n/request.ts`: read cookie → validate against `LOCALES` → merge every
  `messages/<locale>/*.json` into one namespaced object, falling back key-wise to
  `en` so a partial catalog degrades to English instead of rendering a raw key.
- `layout.tsx`: `lang={locale}`, `dir="ltr"` (all five scripts are LTR), wrap
  children in `NextIntlClientProvider`.
- One string moved through `t()` end to end as proof (the app title).

**Done when:** app renders unchanged with `<html lang="en">` sourced from the
locale resolver, and `NEXT_LOCALE=hi` in devtools flips that attribute.

### P2 — Locale round-trip

Files: `src/middleware.ts`, `src/lib/api.ts`, `src/i18n/locale.ts`.

- `middleware.ts`: if `NEXT_LOCALE` absent, set it to `DEFAULT_LOCALE`. Do not
  call the API from middleware.
- `api.ts`: add `language_code` to `CurrentUser`; add `updateMe(payload)` →
  `PATCH /api/v1/auth/me/`; set `Accept-Language` from the current locale on
  every request in `apiFetch`.
- `login()` (`api.ts:122-135`): after fetching `/auth/me/`, write
  `me.language_code` (falling back to `me.tenant.default_language`) to the cookie.
  Note `getCurrentUser`'s `CurrentUser` type is currently narrower than what
  `MeSerializer` actually returns — widen it rather than adding a second type.
- Cookie name is next-intl's `NEXT_LOCALE`; it is **not** Django's
  `django_language`. Don't conflate them.

**Done when:** changing `language_code` via the API and re-logging-in produces the
matching `<html lang>`, and a deliberately-invalid API request returns a
translated error once a non-`en` catalog exists on the backend.

### P3 — Extract existing strings, module by module

Order follows the FE status board (`frontend-plan.md` §7) so converted modules are
the ones being actively worked:

1. `common` + `status` (shared: `StatusPill`, `EmptyState`, nav labels in
   `components/shared/NavItems.ts`, buttons, validation copy)
2. `auth` — `features/auth/*`
3. `settings` — `features/properties/GlobalSettings.tsx`, `PropertySettingsForm.tsx`
4. `properties` — the eight `features/properties/*` components
5. `residents`, `admissions`, `complaints`, `financials`, `dashboard`

Rules while extracting:
- Key names describe *role*, not English text: `residents.list.emptyTitle`, not
  `residents.list.noResidentsYet`.
- Per invariant F3, `StatusPill` maps the backend enum → `status.<enum>` key +
  colour, and renders an unknown status verbatim with a neutral badge rather than
  crashing.
- Do **not** externalise: resident names, property/building/room/bed names,
  audit-log text (PRD "What Does NOT Get Translated"). Room numbers and money
  values pass through untouched.
- Mock data files (`mock-properties.ts`, `mock-residents.ts`, `mock-data.ts`) are
  stand-ins for API data — they represent user-entered content, so their strings
  stay literal and are excluded from the lint rule.

**Done when:** each module's directory passes the lint rule at `error`.

### P4 — Language switcher UI

- **Profile** (`features/profile/UserProfile.tsx` — currently has no language
  field at all): the primary per-user picker. `PATCH /auth/me/` →
  `{ language_code }`, then write the cookie and refresh so the new catalog loads.
- **Settings → Account & Security** (`GlobalSettings.tsx:285-320`): relabel to
  "Default language for new accounts", scope to Owner, and wire to the real
  endpoint from P5. Delete `handleLanguageChange`'s `setTimeout` fake
  (`GlobalSettings.tsx:79-86`).
- Non-active locales render `disabled` with the coming-soon suffix
  (`getLanguageSelectLabel` already produces that label — move it into
  `src/i18n/config.ts`).

**Done when:** switching language in Profile visibly re-renders the app in the
selected locale (verifiable with a stub `hi` catalog) and survives a reload.

### P5 — Close the backend gaps

- **B1:** writable tenant default. Add `default_language` to a writable
  Owner-only serializer/endpoint (`PATCH /api/v1/tenants/current/` or promote it
  on the existing tenant representation — pick whichever matches Module 01's
  established route conventions). Guard with the Owner permission, audit-log the
  mutation (invariant 9), and add a tenant-isolation test (invariant 1) proving
  Owner A cannot change Tenant B's default.
- **B2:** test that `Accept-Language: hi` changes a DRF validation message.
- Per CLAUDE.md workflow: no model change here (`default_language` already
  exists), so no migration or ERD regeneration is needed — but update
  `docs/modules/01-auth-tenancy.md` endpoint table and its Decisions section in
  the same commit.

**Done when:** both tests pass and Module 01's spec matches what was built.

### P6 — Font coverage for Indic scripts

`src/app/layout.tsx:20-28` loads `Noto_Sans` with `subsets: ["latin"]` and a
comment claiming it "covers Devanagari/Telugu/Tamil/Malayalam" with per-glyph
browser fallback. **That comment is wrong on two counts:** a `latin`-only subset
ships no Indic glyphs at all, and Google's `Noto Sans` family has no Telugu,
Tamil, or Malayalam coverage in any subset — those are separate families
(`Noto_Sans_Telugu`, `Noto_Sans_Tamil`, `Noto_Sans_Malayalam`). Devanagari *is* a
valid `Noto Sans` subset.

- V2 (`hi`, `te`): add `devanagari` to the `Noto_Sans` subsets; add
  `Noto_Sans_Telugu`.
- V3 (`ta`, `ml`): add `Noto_Sans_Tamil`, `Noto_Sans_Malayalam`.
- Load script fonts **conditionally per active locale**, not all five always —
  five Indic families in the critical path would wreck the dashboard LCP budget
  (< 2.5s on mid-range Android, `frontend-plan.md` §8).
- Correct the misleading comment now, even before V2, so nobody relies on it.

**Done when:** the comment reflects reality and the conditional-loading approach
is in place (exercised by the stub `hi` catalog).

### P7 — Enforcement

- `eslint-plugin-i18next` (`no-literal-string`) in `frontend/eslint.config.mjs`:
  `warn` globally from P3's start, `error` per converted directory. Ignore
  `mock-*.ts`, test files, and `src/i18n/config.ts` (native language names are
  data, not UI copy).
- Unit test asserting `LOCALES` codes exactly equal the backend `LanguageEnum`
  from the OpenAPI schema (D1).
- Unit test asserting every key present in a non-`en` catalog also exists in `en`
  (catches orphaned keys after refactors).
- CI: lint + these tests wired into the existing gate. `frontend-plan.md` §8
  already promises "build fails on literal JSX strings or missing message keys" —
  P7 is what makes that true.

**Done when:** a PR adding a literal JSX string to a converted module fails CI.

### P8 — Adding a locale later (the payoff)

Adding `hi` should be: drop `messages/hi/*.json`, add the Devanagari subset, flip
`status` to `active` in `src/i18n/config.ts`, add `backend/locale/hi/LC_MESSAGES/
django.po`. **Zero component changes.** If a locale addition requires touching a
component, P1–P7 was done wrong.

---

## 6. Risks

| Risk | Mitigation |
|---|---|
| Extraction is a huge, review-hostile diff | Incremental per-module (D3); lint escalates per directory |
| `next-intl` lags Next 16 | P0 gates the whole plan on verifying this first |
| Keys named after English text; retranslation churn | Role-based key naming enforced in review (P3) |
| Cookie and profile drift (user changes language on another device) | Profile is authoritative; cookie is re-seeded from `/auth/me/` at every login |
| Indic fonts blow the LCP budget | Conditional per-locale loading (P6), Lighthouse CI already gates it |
| Someone "helpfully" translates resident names or audit logs | Explicit do-not-translate list in P3, mirrored from the PRD |
| Registry drifts from the backend enum | CI test asserts equality against the OpenAPI schema (D1/P7) |

---

## 7. Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Library | `next-intl` | Inherited from `frontend-plan.md` Decisions §11 (PRD's `next-i18next` is Pages-Router-only) |
| Locale transport | `NEXT_LOCALE` cookie, no URL prefix | Authed dashboard, no SEO need; avoids rewriting every route |
| Source of truth | User profile `language_code`; cookie is a cache | PRD: preference is per user, not per tenant; cookie keeps SSR off the network |
| Catalog granularity | Per module per locale, merged into namespaces | Keeps `frontend-plan.md` §3.3 layout; next-intl wants one object |
| Missing-key behaviour | Fall back key-wise to `en` | A partial V2 catalog degrades to English, never to a raw key |
| Formatting locale | Always `<code>-IN` | India-only product; lakh/crore grouping and `₹` must be right in every UI language |
| API error language | `Accept-Language` header from the client | `LocaleMiddleware` runs before DRF auth, so it can never see `user.language_code` — the header is the only synchronous lever |
| Tenant default vs. user preference | Two separate UIs (Profile, Settings) | PRD treats per-user as primary and tenant default as an Owner override for *new* accounts |
| Non-active locales in MVP | Listed but `disabled` | F2 wants the switcher shipped; disabling prevents reaching a half-translated UI |
| Extraction strategy | Incremental, lint escalating per directory | 40 components in one diff cannot be reviewed responsibly |
