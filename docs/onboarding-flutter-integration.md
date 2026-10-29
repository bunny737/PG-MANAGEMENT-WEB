# Flutter integration guide: Getting started checklist and tutorial videos

> This guide accompanies [modules/23-getting-started.md](modules/23-getting-started.md), the backend spec, which is
> the source of truth. It explains how the Flutter app uses the Getting started checklist and the tutorial videos.
> All paths are under `{BASE_URL}/api/v1/`, and every call carries the usual `Authorization` and `X-App-*` headers
> ([app-client-flutter-integration.md](app-client-flutter-integration.md) §2).

## 0. What the app must do

1. On the staff home screen, call `GET /onboarding/checklist/?property=<active property id>`. Leave `property`
   out when the app shows "All properties". Render the result as described in §2.
2. Show nothing in these cases:
   - `dismissed` is true.
   - `status` is `no_actions`.
   - The request is still loading.
3. Point each step's button to the screen in §3, using the step's `params`. Don't compute progress yourself.
   Show `progress.done / progress.total` from the response.
4. After any of these actions, call the checklist again (§4):
   - creating or deleting a property, building, floor or room
   - an admission
   - an expense
   - dismissing or restoring the checklist
5. Show `GET /help/videos/` on a Help screen. Play a video in a YouTube player (§5). Offline, show a notice and
   never try to stream.

## 1. Endpoints

| Call | Purpose | Response |
|---|---|---|
| `GET /onboarding/checklist/?property=` | The checklist | 200 JSON (below). 404 for a property the user can't see |
| `POST /onboarding/checklist/dismiss/` | Hide the checklist for this user, on every device | 204 |
| `DELETE /onboarding/checklist/dismiss/` | Show the checklist again | 204 |
| `GET /help/videos/?language=te` | Tutorial catalog | 200 JSON. 400 for an unknown language |
| `GET /auth/me/` | Includes `onboarding_dismissed` (bool) | |

- **Who can call them:** Owner, Manager and Receptionist. Residents get 403.
- **Dismiss and restore are idempotent.** A repeated call is harmless.

```json
{
  "status": "in_progress",
  "dismissed": false,
  "target_property": { "id": "8c1…", "name": "Greenwood PG" },
  "progress": { "done": 2, "total": 5 },
  "next_step": "add_floor",
  "steps": [
    { "key": "add_property",  "required": true,  "done": true,  "permitted": true, "blocked_by": null,
      "params": {}, "video_topic": "add_property" },
    { "key": "add_building",  "required": true,  "done": true,  "permitted": true, "blocked_by": null,
      "params": { "property_id": "8c1…" }, "video_topic": "add_building" },
    { "key": "add_floor",     "required": true,  "done": false, "permitted": true, "blocked_by": null,
      "params": { "property_id": "8c1…", "building_id": "b07…" }, "video_topic": "add_floor" },
    { "key": "add_room",      "required": true,  "done": false, "permitted": true, "blocked_by": "add_floor",
      "params": { "property_id": "8c1…" }, "video_topic": "add_room" },
    { "key": "admit_resident","required": true,  "done": false, "permitted": true, "blocked_by": "add_floor",
      "params": { "property_id": "8c1…" }, "video_topic": "admit_resident" },
    { "key": "record_expense","required": false, "done": false, "permitted": true, "blocked_by": null,
      "params": { "property_id": "8c1…" }, "video_topic": "expenses" }
  ]
}
```

- **Without `property`:** the server picks the property the user can best act on now. `target_property` names
  it, and every `params` points inside it.
- **`target_property` is null** when the user has no property yet. The heading is then generic ("Set up your
  PG").

## 2. Rendering

### Card

| `dismissed` | `status` | Show |
|---|---|---|
| true | any | nothing |
| false | `no_actions` | nothing |
| false | `in_progress` | the checklist |
| false | `completed` | "You're all set" with a **Hide** button that calls dismiss. Never hide it automatically |

### Each row

| Row state | Show |
|---|---|
| `done` | a tick, plus ▶ if a video exists for `video_topic`. No button, no "Ask your owner" |
| not done, `permitted`, `blocked_by == null` | the step's button. Make it primary when `key == next_step` |
| not done, `permitted`, `blocked_by != null` | greyed out, "After: {label of blocked_by}" |
| not done, not `permitted` | "Ask your owner" |

- **Steps with `required: false`** (`record_expense`) go in a separate "Also try" group. Show them only when
  permitted and not done.
- **Step keys are a fixed contract:** `add_property`, `add_building`, `add_floor`, `add_room`,
  `admit_resident`, `record_expense`. The app translates the labels in its own catalogs (en and te).

## 3. Step → screen

| Key | Screen | Uses |
|---|---|---|
| `add_property` | Add property | — |
| `add_building` | Add building for property | `property_id` |
| `add_floor` | Add floor in building | `property_id`, `building_id` |
| `add_room` | Add room on floor (with beds) | `property_id`, `floor_id` |
| `admit_resident` | Admission wizard, preset to the property (no bed preselected) | `property_id` |
| `record_expense` | Expenses, scoped to the property, add sheet | `property_id` |

If an id a screen needs is missing, the step is blocked anyway. Show no button.

## 4. When to refetch

Call `GET /onboarding/checklist/` again:
- when the home screen appears
- after creating or deleting a property, building, floor or room
- after an admission
- after creating or deleting an expense
- after dismiss or restore

After dismiss or restore, also call `GET /auth/me/`.

The app may skip the checklist request when the cached `/auth/me/` says `onboarding_dismissed: true`.

## 5. Tutorial videos

```json
{ "requested_language": "te",
  "available_languages": ["en", "hi", "te"],
  "videos": [ { "topic": "add_property", "language": "te", "title": "…", "description": "…",
                "youtube_id": "dQw4w9WgXcQ", "duration_seconds": 120 },
              { "topic": "add_floor", "language": "en", "title": "…", "description": "",
                "youtube_id": "…", "duration_seconds": null } ] }
```

- **Request:** send `?language=` set to the app language. If you leave it out, the server uses the user's
  `language_code`.
- **Language picker:** offer `available_languages` plus English and the app language. A language can have videos
  before the app's UI is translated into it.
- **One video per topic:** the server returns the requested language, else English, and never a third language.
- **Fallback label:** when `video.language != requested_language`, show "Shown in English — తెలుగు version
  coming soon".
- **Player:** use `youtube_player_iframe` with the `youtube_id`. Videos are unlisted YouTube uploads.
- **Thumbnails:** `https://i.ytimg.com/vi/{youtube_id}/mqdefault.jpg`.
- **Offline:** show the "Videos play when you're back online" notice instead of the player.
- **Watch buttons:** a ▶ appears next to a checklist row or an empty list only when a video exists for its topic.
  Topics: `overview`, the five required step keys, `property_settings`, `expenses`, `billing`, `staff`.
- **Caching:** you can cache the list for 5 minutes (`Cache-Control: private, max-age=300`).

## 6. Empty screens

Each empty list should say what to do next. Show its button only when the user holds the permission:

| Screen | Button | Permission | Video topic |
|---|---|---|---|
| Properties | Add property | `manage_properties` | `add_property` |
| Floors | Add floor | `manage_rooms_beds` | `add_floor` |
| Residents | Admit resident | `manage_admissions` | `admit_resident` |
| Expenses | (existing add button) | `manage_expenses` | `expenses` |

Take the permissions from `/auth/me/` `permissions`, never from the role name.
