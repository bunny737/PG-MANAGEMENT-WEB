# Module: Getting Started (setup checklist, empty-state hints, tutorial videos)

> Keep this file in sync with the code AT ALL TIMES.
> If the code and this file disagree, this file is wrong — fix it in the same commit.

**Status:** Done
**Phase:** 3
**PRD reference:** none — owner request 2026-10-28, not in PRD v2
**Depends on:** 01, 02, 03, 04, 05, 20
**Blocks:** none

## Purpose
A new owner signs up and lands on a dashboard that looks the same as a fully set-up account, with nothing
saying what to do next. This module adds three things:
- a **Getting started checklist** on the dashboard (property → building → floor → rooms and beds → first
  admission, plus an optional first expense)
- **empty-state hints**: empty screens say what to do next, with a permission-gated CTA and a "Watch how"
  tutorial
- a **Help & tutorials** page of short videos in the user's language

Everything comes from one API, so the web/PWA and the Flutter app behave the same way. The Flutter guide is
[../onboarding-flutter-integration.md](../onboarding-flutter-integration.md).

The server computes the checklist because a client can't do it cheaply. Resident data is per-property, comes as
a full list and needs `view_resident_profile`. The hierarchy needs one layout call per property. Dismissal also
has to sync across devices.

## Data model (as-built)
```
Table: tutorial_videos          (platform-level — no tenant_id, no RLS; like notification_templates)
  id                bigserial
  topic             overview | add_property | add_building | add_floor | add_room | admit_resident
                    | property_settings | expenses | billing | staff
  language          settings.LANGUAGES (en, hi, te, ta, ml)
  title             varchar(120)
  description       text
  youtube_id        varchar(11), ^[A-Za-z0-9_-]{11}$ — an unlisted YouTube video's id
  duration_seconds  int NULL
  sort_order        smallint
  is_active         bool
  audience          jsonb list of roles ⊆ {owner, manager, receptionist}; default all three
  updated_by        FK → users NULL (SET_NULL)
  created_at, updated_at
  UNIQUE (topic, language)

users.onboarding_dismissed_at   timestamptz NULL   — when this user hid the checklist; NULL = shown
```
Account deletion (Module 22) classes `onboarding.TutorialVideo` as platform data.

## API endpoints
All of these require authentication as tenant staff (`IsTenantStaff`: Owner, Manager or Receptionist).
Residents and Super Admin get 403.
```
GET     /api/v1/onboarding/checklist/?property=     the checklist (below)
POST    /api/v1/onboarding/checklist/dismiss/       hide it for this user          204
DELETE  /api/v1/onboarding/checklist/dismiss/       show it again                  204
GET     /api/v1/help/videos/?language=              tutorial catalog                Cache-Control: private, max-age=300
```
`GET /auth/me/` also returns `onboarding_dismissed` (bool).

Checklist response:
```json
{ "status": "in_progress", "dismissed": false,
  "target_property": {"id": "…", "name": "…"},
  "progress": {"done": 2, "total": 5},
  "next_step": "add_floor",
  "steps": [ {"key": "add_property", "required": true, "done": true, "permitted": true,
              "blocked_by": null, "params": {}, "video_topic": "add_property"}, … ] }
```
The response always lists all six steps, in order.

Videos response: `{requested_language, videos: [{topic, language, title, description, youtube_id, duration_seconds}]}`.
When English stood in for a topic, `video.language` differs from `requested_language`. Clients use that to show
"Shown in English — తెలుగు version coming soon".

## Business rules
Each rule has a test in `apps/onboarding/tests/`. The code is `apps/onboarding/checklist.py`.

**Steps and predicates**
1. The required steps, in order, are `add_property`, `add_building`, `add_floor`, `add_room`,
   `admit_resident`. The only optional step is `record_expense`.
2. Each step's `done` is an existence check, with an explicit `tenant_id` filter on top of property visibility
   and RLS:
   - `add_property`: the caller has at least one visible property.
   - `add_building`: the target property has a building.
   - `add_floor`: the target has a floor.
   - `add_room`: the target has a room **with at least one bed**.
   - `admit_resident`: an `Admission` exists for a resident of the target.
   - `record_expense`: the target has a non-deleted expense.

   No counts are returned.
3. `permitted` means the caller holds the step's permission:
   - `add_property` needs `manage_properties`.
   - `add_building`, `add_floor` and `add_room` need `manage_rooms_beds`.
   - `admit_resident` needs `manage_admissions`.
   - `record_expense` needs `manage_expenses`.

   Permissions resolve through `permissions_for_user`, so module-access overrides apply.
4. A required step's `blocked_by` is the first earlier required step that isn't done. So only the first not-done
   required step is ever unblocked.
5. `record_expense` only needs a property. Its `blocked_by` is `add_property` when there is no target property,
   and `null` otherwise.

**Counted set, next step and status**

6. The **counted set** is the permitted required steps, blocked ones included. It alone drives `progress`
   (numerator and denominator), `next_step` and `status`. Optional steps are never counted.
7. `next_step` is the first counted step that is not done and has `blocked_by = null`, or `null` if there is none.
8. `status` is checked in this order:
   1. The counted set is empty → `no_actions`.
   2. Every counted step is done → `completed`.
   3. `next_step` is set → `in_progress`.
   4. Otherwise → `no_actions`. The first not-done step belongs to someone else.

**Target property**

9. With `?property=`, the target is that property. A property the caller can't see, or a malformed id, returns 404.
10. Without `?property=` ("All properties"), one query picks the target:
    - It ranks every visible property for this caller, using `Exists()` annotations and a `Case` built from the
      caller's permitted steps.
    - Rank 0: the caller can act now. Rank 1: the next step belongs to someone else. Rank 2: complete.
    - Ties are broken by `(created_at, id)`.
11. `params` carry the ids each step's screen needs: the property, the oldest building (for `add_floor`) and the
    oldest floor (for `add_room`). The request is a constant number of queries, and a test checks that 1 and 10
    properties issue the same number.

**Dismissal**

12. `dismissed` changes only through dismiss and restore, never automatically. Finishing every step does not
    dismiss the checklist.
13. Dismiss and restore are idempotent. A repeated POST keeps the first timestamp, and a DELETE on a shown
    checklist does nothing. A conditional UPDATE does the change, and an audit row (`onboarding.dismissed` /
    `onboarding.restored`, before/after) is written only when something changes.
14. Dismissal is per user. A newly invited manager gets their own checklist.

**Videos**

15. The server first narrows the catalog to `is_active` videos whose `audience` contains the caller's role.
    Only then does it pick each topic's video in the requested language, falling back to English. A video the
    caller can't see never hides an English one they can.
16. The requested language is `?language=`, or else the user's `language_code`. There is never a third language
    (not even the tenant default). A language outside `settings.LANGUAGES` returns 400.
17. Videos are managed only in Django admin, by a Super Admin, and every change is audit-logged as a platform
    record. The API has no write methods (405).

**Tenant isolation**

18. Another tenant's data never ticks a step, and another tenant's property id returns 404.

## Permissions
| Role | Checklist steps it can act on |
|---|---|
| Owner | all |
| Manager (default access) | building, floor, room, admission, expense — never property |
| Manager (module-access override) | whatever the override grants |
| Receptionist (default) | none → `no_actions`, card hidden |

Help & tutorials is open to every staff role.

## Frontend
- **`GettingStartedCard`** (`features/onboarding/`) sits at the top of the dashboard on desktop and phone.
  - It sends the active property (`null` = All properties).
  - It is hidden when `dismissed` or `no_actions`.
  - It renders nothing while loading, so dashboards that never show the card don't flash a skeleton.
  - It skips the request entirely when the cached profile already says `onboarding_dismissed`.
- **Rows:**
  - done: a tick, plus ▶ when a video exists
  - open: a CTA (primary on `next_step`)
  - blocked: "After: …"
  - not permitted: "Ask your owner"
- **CTA routes** (`features/onboarding/routes.ts`) are built from `params`:
  - `/properties/add`
  - `/properties/{p}/buildings/add`
  - `/properties/{p}/buildings/{b}/floors/add`
  - `/properties/{p}/floors/{f}/rooms/add`
  - `/admissions?property={p}`
  - `/expenses?property={p}`
- **`EmptyState`** (`components/shared/`) is used on Properties (desktop and phone), Floors, and Residents
  (desktop and phone). Its CTA is gated by `can(permission)`. Expenses adds only the "Watch how" link, because
  its add button opens a sheet. The property overview shows a "Review this property's settings" hint until the
  first bed is occupied, to users with `manage_property_settings`.
- **`/help`** shows the video grid with a language selector (active locales), the per-video fallback note,
  "Videos coming soon" when there are none, "Show the checklist again" (only when dismissed) and a support
  link. It is the last sidebar item and appears under More on phones. It has `landing: false`, so
  `firstAllowedRoute` never sends anyone there.
- **Player:** `VideoPlayerDialog` uses a lazy `youtube-nocookie.com` iframe and shows an offline notice
  instead when offline.
- **CSP** additions: `frame-src https://www.youtube-nocookie.com` and `img-src https://i.ytimg.com`.
- **Refresh:**
  - `afterHierarchyChange()` runs after property, building, floor and room create/delete.
  - `afterBedChange`, `afterAdmission` and `afterExpenseChange` also invalidate `onboarding`.
  - `afterOnboardingDismissChange()` invalidates the checklist and refreshes the session profile.
- **i18n:** `messages/{en,te,hi}/onboarding.json` and `common.nav.help`.

## Open questions / Decisions
- [DECISION 2026-10-28, owner] Videos are **unlisted YouTube** uploads, and the app stores only the id. That
  means free hosting and adaptive streaming on slow networks, and Flutter can use `youtube_player_iframe`.
  Anyone with the link can watch, which is acceptable for how-to content.
- [DECISION 2026-10-28, owner] Dismissal is **per user, synced** through the server, not per device.
- [DECISION 2026-10-28] **Rooms and beds are one step.** `AddRoomForm` always sends `auto_create_beds: true`
  and the web has no separate add-bed flow. A room with no beds (possible over the API) leaves the step not done.
- [DECISION 2026-10-28] **"First resident" means an admission** (check-in sets Active). Reserved and inquiry
  residents don't count. The step is sticky: Admission is one-to-one and PROTECT, and residents can't be
  deleted, so vacating never un-ticks it. Hierarchy steps reflect current data, so deleting the last building
  un-ticks `add_building`.
- [DECISION 2026-10-28] **No "review settings" step.** Nothing reliably records that settings were reviewed
  (`updated_at > created_at` isn't proof), and dismissing must not fake it. Settings get a video topic and a
  hint instead.
- [DECISION 2026-10-28] **`add_building` usually ticks itself.** `PropertyViewSet.perform_create`
  auto-creates a "Main Building" (Module 02). The step stays in the list because a property whose buildings
  were deleted needs it.
- [DECISION 2026-10-28] **Step keys are a contract.** Clients translate the labels, and the server returns keys
  only. Clients also map keys and `params` to screens.
- [DECISION 2026-10-28] **Expenses and admissions CTAs use `?property=`.** `useActiveProperty()` already adopts
  `?property=` as the active property, so a plain link opens Expenses scoped to the property the card names.
  The CTA doesn't set the store itself.
- [DECISION 2026-10-28] **Help reads `dismissed` from the checklist query**, so there is one source of truth.
  `onboarding_dismissed` on `/auth/me/` only lets the dashboard skip the request. Dismiss and restore refresh
  both.

## Changelog
- 2026-10-28  Built: TutorialVideo, `users.onboarding_dismissed_at`, the checklist / dismiss / videos endpoints,
              the dashboard card, EmptyState hints, /help, CSP, the Flutter guide.
