# Module: Notifications

> Keep this file in sync with the code AT ALL TIMES.
> If the code and this file disagree, this file is wrong — fix it in the same commit.

**Status:** Done
**Phase:** 3 (MVP) + V2 (templates, scheduling, multi-channel)
**PRD reference:** Module 18 (Notifications) — MVP scope: email only; V2 scope:
SMS/WhatsApp/push, templates, scheduling
**Depends on:** 08, 09
**Blocks:** none

## Purpose
The platform sends notifications for four business events (PRD MVP): a welcome
notification on signup, trial-expiry reminders at two configurable offsets, an
invoice-issued notice, and a payment receipt. Every attempt — sent, failed, or
skipped — is recorded so ops can see what went out without digging through
logs.

V2 (this revision) turns the MVP's hardcoded Python email functions into a
generic, multi-channel dispatch system:
- **Templates**: wording lives in the DB (`NotificationTemplate`), editable by
  a Super Admin via Django admin — no code deploy to change copy or add a
  language.
- **Channels**: email (unchanged behavior) and **push via Firebase Cloud
  Messaging** are live; SMS and WhatsApp have the same pluggable interface
  but are stubbed (no vendor chosen yet — PRD explicitly defers this).
- **Scheduling**: recurring sweeps (e.g. the trial-reminder scan) are now
  `django-celery-beat` `PeriodicTask` rows — a Super Admin can retime them
  without a deploy — plus a new `ScheduledNotification` model for one-off,
  send-at-a-specific-time notifications.
- **API**: a resident/owner/staff user can see their own notification history
  and manage(opt out of) optional notification types; a
  `push-subscriptions` endpoint registers FCM device tokens. `NotificationLog`
  itself stays admin-only for the full, cross-recipient view (unchanged from
  MVP).

## Data model (as-built)

```
Table: notification_logs                        (RLS enforced, app: apps.notifications)
  id                    uuid PK
  tenant_id             uuid              (RLS)
  notification_type     welcome | trial_expiry_reminder | invoice_issued | payment_receipt
  channel                email | sms | whatsapp | push               [V2]
  recipient_email        email, blank (blank unless channel=email and recipient has an email)
  recipient_user         FK -> accounts.User, null                   [V2]
                          — set whenever the recipient is a real login account
                          (Owner/Manager/Receptionist), regardless of channel;
                          null for Resident recipients (no login account yet)
  subject                varchar(255), blank
  status                 sent | failed | skipped
  reference               varchar(255), blank, indexed
                          — 'user:<uuid>' | 'invoice:<uuid>' | 'payment:<uuid>'
                          | 'tenant_trial:<uuid>:<days_before>' | 'scheduled:<uuid>'
                          also doubles as the trial-reminder idempotency key
  note                   text, blank            (error message, or why skipped)
  sent_at                datetime, null
  created_at / updated_at

Table: notification_templates                   (NOT tenant-scoped — platform-wide, no RLS)  [V2]
  id                    uuid PK
  notification_type     matches a key in apps.notifications.registry.NOTIFICATION_TYPES
  channel                email | sms | whatsapp | push
  language               matches settings.LANGUAGES
  subject                varchar(255), blank (channels with no subject concept leave this blank)
  body                   text — rendered with Django's template engine, autoescape off
  is_active              bool
  created_at / updated_at
  unique(notification_type, channel, language)

Table: notification_preferences                 (RLS enforced, app: apps.notifications)  [V2]
  id                    uuid PK
  tenant_id             uuid              (RLS)
  user                   FK -> accounts.User
  notification_type      matches a registry key marked optional=True
  channel                 email | sms | whatsapp | push
  enabled                 bool, default True
  unique(user, notification_type, channel)
  # Opt-out model: absence of a row means "enabled" — a user who never
  # touches this keeps receiving everything they get today.

Table: push_subscriptions                        (RLS enforced, app: apps.notifications)  [V2]
  id                    uuid PK
  tenant_id             uuid              (RLS)
  user                   FK -> accounts.User
  fcm_token               varchar(255), unique
  device_type             web | android | ios
  last_seen_at            datetime, auto_now

Table: scheduled_notifications                    (RLS enforced, app: apps.notifications)  [V2]
  id                    uuid PK
  tenant_id             uuid              (RLS)
  notification_type      matches a registry key
  recipient_user          FK -> accounts.User
  context                  JSON — rendered into the template
  channels                 JSON list — empty means "use the registry default for this type"
  send_at                  datetime, indexed
  status                   pending | sent | cancelled
  created_by               FK -> accounts.User, null (ops author, via admin)

Table: platform_config  (Module 01, extended by MVP)
  trial_reminder_first_days_before   positive int, default 15
  trial_reminder_second_days_before  positive int, default 5
  # invariant 10: offsets from trial_ends_at, not absolute "Day 45/55" — stays
  # correct if a Super Admin edits trial_days.

django_celery_beat's own tables (PeriodicTask, CrontabSchedule, IntervalSchedule)
seed two rows via migration 0004: a daily 9am crontab sweep for trial-expiry
reminders, and a 1-minute interval poll for due ScheduledNotification rows.
Both are Super-Admin-editable via Django admin afterwards.
```

## API endpoints

```
GET     /api/v1/notifications/history/                 — current user's own NotificationLog rows
GET     /api/v1/notifications/preferences/              — effective opt-in state for optional types
POST    /api/v1/notifications/preferences/              — upsert one or more preference rows
GET     /api/v1/notifications/push-subscriptions/       — current user's registered devices
POST    /api/v1/notifications/push-subscriptions/       — register/refresh an FCM token (upserts on token)
DELETE  /api/v1/notifications/push-subscriptions/{id}/  — unregister a device
```
`NotificationLog` itself (the full, cross-recipient view), `NotificationTemplate`
(content), and `ScheduledNotification` (one-off authoring) remain Django-admin
only — matching the MVP's original "no dedicated cross-tenant API" decision
(see Decisions below for why this wasn't extended into a full CRUD API).

## Business rules (each maps to a test)
1. Signup dispatches the existing verification email
   (`apps.accounts.emails.send_verification_email`, unchanged) via a Celery
   task (`apps.accounts.tasks.send_welcome_email_task`), deferred with
   `transaction.on_commit`. The task logs one `NotificationLog(type=welcome)`
   row via `services.record_sent` — no second email is sent (unchanged from
   MVP; welcome does not go through the V2 template/channel system).
2. Issuing an invoice (`InvoiceViewSet.issue`) and recording a payment
   (`services.record_payment`) both call `services.notify()`, which resolves
   channels from `registry.channels_for(notification_type)` (`invoice_issued`
   and `payment_receipt` both include `email` and `push`), renders each
   channel's active `NotificationTemplate`, and logs one `NotificationLog`
   row per channel attempt.
3. A resident with no `email` on file is `skipped` (not `failed`) on the
   email channel — fail-open, same discipline as the MVP. The push channel
   for a Resident recipient is *always* skipped (`'Recipient has no linked
   login account'`) since residents have no `User` row yet
   (`apps.residents.models.Resident`'s own docstring; same limitation
   `ComplaintViewSet.raise_complaint` already documents).
4. A broken SMTP server or a Firebase send error logs `status=failed` with
   the exception message in `note`; neither ever raises back into the
   request/task that triggered it.
5. Trial-expiry reminders are driven by a daily `django-celery-beat`
   `PeriodicTask` (`notifications.trial_expiry_reminders_sweep`, seeded by
   migration 0004) calling `tasks.run_due_sweep('trial_expiry_reminders')`,
   which dispatches `services.due_trial_reminders()`'s matches exactly like
   the original MVP's management command did. The
   `send_trial_expiry_reminders` command itself is kept unchanged as a
   manual/ops-triggered fallback — both paths call the same
   `services.due_trial_reminders()` + `send_trial_expiry_reminder_task`.
6. Trial reminders are idempotent: `reference='tenant_trial:<tenant>:<offset>'`
   is checked before sending, so re-running the sweep (or a retry) never
   double-sends. Unchanged from MVP.
7. `services.notify()` resolves the recipient's `language_code` (falling back
   to `'en'` when absent, e.g. for a Resident) and picks the matching
   `NotificationTemplate`, falling back to the English template if the
   requested language has no active row for that (type, channel) — a missing
   translation degrades gracefully rather than crashing or sending nothing
   (invariant 7).
8. `NotificationPreference` only suppresses a channel for registry types
   marked `optional=True` (today: `invoice_issued` only) — `welcome`,
   `trial_expiry_reminder`, and `payment_receipt` cannot be disabled by the
   recipient (a payment receipt is not optional).
9. `channels/push.py` looks up `PushSubscription` rows for the recipient and
   sends to every registered token via `firebase_admin.messaging.send()`.
   An `UnregisteredError` (stale/uninstalled-app token) prunes that
   `PushSubscription` row so it's never retried again. If no Firebase
   credentials are configured (`FIREBASE_CREDENTIALS_PATH`/`_JSON`, both
   blank in dev/test), the channel logs `skipped` — same fail-open
   discipline as every other channel.
10. `dispatch_scheduled_notifications` (polled every minute by a
    `django-celery-beat` `IntervalSchedule`, seeded by migration 0004) sends
    every `PENDING` `ScheduledNotification` whose `send_at` has passed,
    through the same `services.notify()` path, then flips it to `SENT`.
11. All RLS-enforced tables here (`notification_logs`,
    `notification_preferences`, `push_subscriptions`,
    `scheduled_notifications`) have an isolation test.
    `notification_templates` is deliberately NOT tenant-scoped (see
    Decisions).

## Permissions
New self-scoped permissions (`apps/core/roles.py`), following the same
pattern as `view_own_profile`/`view_own_invoices`: `view_own_notifications`
and `manage_notification_preferences`, granted to every `TENANT_ROLES` member
(Owner/Manager/Receptionist/Resident — every tenant role receives some
notification type). Registering a push device needs no special permission
(same treatment as editing your own profile). `NotificationTemplate`,
`NotificationLog` (full view), and `ScheduledNotification` (authoring) stay
Django-admin-only — superuser login, matching the MVP's original decision for
`NotificationLog`.

## Edge cases handled
- Signup does not send two emails — unchanged from MVP.
- A tenant whose two trial-reminder offsets are set equal by a Super Admin
  fires both (deduped separately by `reference`) — unchanged from MVP.
- Running the trial-reminder sweep (via beat or the manual command) after a
  tenant has left `TRIAL` status sends nothing further — unchanged from MVP.
- A `ScheduledNotification` already `SENT` or `CANCELLED` is never
  re-dispatched — the poll task only selects `PENDING` rows, and
  `_dispatch_one_scheduled_notification` re-checks status under the row's
  own tenant context before sending (defends against a concurrent run).
- A channel the registry lists for a type (e.g. `push` for `invoice_issued`)
  but with no active template configured logs a clean `skipped`
  (`'No active template configured...'`), never a crash — this is how new
  channels/types can be *declared* before they're fully authored.
- `CELERY_TASK_ALWAYS_EAGER=True` in dev/test — unchanged; `celery-beat` is a
  separate Docker service (`docker-compose.yml`) using
  `django_celery_beat.schedulers:DatabaseScheduler` so PeriodicTask edits in
  Django admin take effect without a restart.

## Open questions / Decisions

### From the MVP (unchanged)
- [DECISION 2026-07-04] **Welcome email == verification email** — see prior
  changelog entry; still true in V2 (`welcome` does not route through
  `services.notify()`/templates).
- [DECISION 2026-07-04] **Welcome task lives in `apps.accounts`, not
  `apps.notifications`** — unchanged; still avoids the circular import.
- [DECISION 2026-07-04] **Invoice-issued notification fires on `issue`, not
  `create`** — unchanged.
- [DECISION 2026-07-04] **Trial-reminder offsets are config, not the PRD's
  literal "Day 45/55"** — unchanged (`PlatformConfig`).
- [DECISION 2026-07-04] **`transaction.on_commit` everywhere a task is
  dispatched after a DB write** — unchanged.

### V2 (this revision)
- [DECISION 2026-09-17] **Templates are platform-wide, not per-tenant.**
  `NotificationTemplate` has no `tenant_id`/RLS — every tenant's residents
  get the same wording. A per-tenant override (branding, tone) was
  considered and explicitly deferred: it would need a new override table,
  RLS-scoped resolution logic, and an Owner-facing UI/permission, for a
  need nobody has asked for yet. Revisit if an Owner asks to customize their
  own resident-facing copy.
- [DECISION 2026-09-17] **Push is built for real (Firebase Cloud Messaging);
  SMS/WhatsApp are stubbed.** FCM covers both Web Push (the Serwist service
  worker already planned in `docs/frontend-plan.md` §5.2) and native
  Android push later (the locked mobile stack is FCM-compatible by
  default) from one backend integration, and the owner explicitly asked for
  Firebase. SMS/WhatsApp need a vendor decision (MSG91, Gupshup, Twilio —
  all viable for India) that hasn't been made; `channels/sms.py` and
  `channels/whatsapp.py` exist with the same interface but only log
  `skipped` until a provider is chosen. This is a vendor decision for the
  owner, not something to guess at.
- [DECISION 2026-09-17] **Push cannot reach Resident recipients yet.**
  `PushSubscription.user` is an `accounts.User` FK, but
  `apps.residents.models.Resident` has no linked login account (documented
  on that model). `channels/push.py` checks `isinstance(recipient_user,
  User)` and skips with an explicit note otherwise, rather than silently
  dropping the notification or crashing. `invoice_issued`/`payment_receipt`
  (Resident-facing) therefore only ever succeed on the `email` channel today;
  `trial_expiry_reminder` (Owner-facing) can use push once a device is
  registered. Revisit once Module 04 adds resident login.
- [DECISION 2026-09-17] **`django-celery-beat` added as a new dependency**
  (pinned `==2.9.*` — the 2.7 line pinned in the original plan doesn't
  support Django 5.2). Recurring sweeps become DB-editable `PeriodicTask`
  rows (Super Admin can retime without a deploy) instead of "run this via
  external cron" — a materially easier ops story, worth the new dependency.
  A separate `celery-beat` Docker service runs the scheduler
  (`docker-compose.yml`).
- [DECISION 2026-09-17] **Self-scoped history/preferences API, not a full
  CRUD API.** `NotificationLog`/`NotificationTemplate`/`ScheduledNotification`
  stay Django-admin-only for the cross-recipient/authoring views (same
  treatment the MVP gave `NotificationLog` and Module 13 gave
  `SubscriptionPayment`); only "my own notifications" and "my own
  preferences/devices" got a real API, since that's what the frontend
  (`docs/frontend-plan.md` FE-14, still not started) and the flagged
  `push_subscriptions` prerequisite actually need.
- [DECISION 2026-09-17] **`NotificationLog.recipient_user` added
  alongside `recipient_email`.** Needed so `/notifications/history/` can
  find "logs about me" for non-email channels too (push/sms/whatsapp logs
  never populate `recipient_email`, which is email-channel-specific
  display data). Null for Resident recipients, same limitation as push.
- [DECISION 2026-09-17] **Templates use Django template syntax
  (`{{ name }}`), not the MVP's `%(name)s` Python string formatting**,
  rendered with `autoescape=False` (these are plain-text bodies, not HTML).
  This is a deliberate divergence from invariant 7's literal "gettext
  server-side" mechanism: content now lives in DB rows editable without a
  deploy, which is the actual goal of invariant 7 (translatable, never
  hardcoded) — gettext's `.po` catalogs remain the mechanism for every
  *other* user-facing string in the codebase, just not for notification
  template bodies now that those are Super-Admin-authored content, not
  code. The `0003_seed_notification_templates` migration ports the
  MVP's exact existing English/Telugu wording (converted from `%(x)s` to
  `{{ x }}`) verbatim from the original `emails.py` and the approved
  `locale/te/LC_MESSAGES/django.po` translations, so nothing regresses.
- [DECISION 2026-09-17] **`apps/notifications/emails.py` removed.** Its
  three content-building functions are superseded by `NotificationTemplate`
  rows (seeded from their exact former content); nothing else imported this
  module.
- [OPEN] Password-reset and staff-invite emails (`apps.accounts.emails`)
  stay synchronous and outside `NotificationLog`/the template system —
  unchanged from MVP's original scope decision.
- [OPEN] SMS/WhatsApp provider selection — see the stubbing decision above.
- [OPEN] Django admin's visibility into RLS-protected tables
  (`NotificationLog`, `PushSubscription`, `NotificationPreference`,
  `ScheduledNotification`) depends on the Postgres session having
  `app.is_super_admin` set; that GUC is only ever set by
  `TenantJWTAuthentication` (DRF requests), never by Django's own
  session-based admin auth. This is a pre-existing, codebase-wide condition
  (every other admin-registered RLS model — `Invoice`, `Payment`,
  `SubscriptionPayment`, `Resident`, etc. — has the same property, not
  something introduced here) and out of scope for this module to fix.

## Changelog
- 2026-06-xx  Created stub.
- 2026-07-04  Built: `NotificationLog` model (RLS), two `PlatformConfig`
  trial-reminder-offset fields, `apps.notifications.{emails,services,tasks}`,
  a Celery task per notification (welcome lives in `apps.accounts.tasks`),
  the `send_trial_expiry_reminders` management command, hooks in
  `SignupSerializer.create`, `InvoiceViewSet.issue`, and
  `billing.services.record_payment`. `CELERY_TASK_ALWAYS_EAGER` enabled in
  `config/settings/dev.py`. 11 new tests. Full suite (369) green. Also fixed
  a stale `celery` Docker image (see Decisions).
- 2026-09-17  **V2**: `NotificationTemplate` (DB-backed, admin-editable
  content, Django-template-rendered) + seed migration porting the MVP's
  exact EN/TE wording; `apps.notifications.registry` (notification-type
  catalog: channels, optional flag, context vars); generic
  `services.notify()`/`channels/{base,email,push,sms,whatsapp}.py` dispatch
  replacing the three per-type Celery tasks; `PushSubscription` +
  `channels/push.py` (Firebase Cloud Messaging, token pruning on
  `UnregisteredError`); `django-celery-beat` (new dependency, `celery-beat`
  Docker service) driving a generalized `run_due_sweep` (trial reminders,
  seeded as a daily `PeriodicTask`) plus a new `ScheduledNotification`
  model + minute-polled `dispatch_scheduled_notifications` for one-off
  sends; `NotificationPreference` (opt-out for `optional=True` types) and
  `NotificationLog.recipient_user`/`channel` fields; new self-scoped API
  (`/notifications/history/`, `/notifications/preferences/`,
  `/notifications/push-subscriptions/`) and matching
  `view_own_notifications`/`manage_notification_preferences` permissions;
  removed `apps/notifications/emails.py` (superseded). 34 new tests (45
  total in this app). Full suite (507) green. ERD regenerated.
- 2026-09-17  **V2 follow-up**: mobile stack pivoted from native
  Android/iOS to Flutter (owner decision — see `CLAUDE.md` and
  `docs/frontend-plan.md` §1/§3.1a); `PushSubscription.DeviceType.IOS`
  value corrected from `'iOS'` to `'ios'` (consistency with the other
  lowercase choices, fixed before any client shipped against it);
  `channels/push.py` now sends `notification_type`/`reference` as the FCM
  message's `data` payload so a client can deep-link on tap (channel
  interface extended with matching, currently-unused kwargs on
  email/sms/whatsapp for a consistent polymorphic signature); added
  `docs/push-notifications-integration.md` (web + Flutter FCM setup guide).
  1 new test. Full suite still green.
