# Module: Notifications

> Keep this file in sync with the code AT ALL TIMES.
> If the code and this file disagree, this file is wrong — fix it in the same commit.

**Status:** Done
**Phase:** 3
**PRD reference:** Module 18 (Notifications) — MVP scope: email only
**Depends on:** 08, 09
**Blocks:** none

## Purpose
The platform sends four transactional emails end-to-end (PRD MVP): a welcome
email on signup, trial-expiry reminders at two configurable offsets, an
invoice-issued notice to the resident, and a payment receipt to the resident.
Every attempt — sent, failed, or skipped — is recorded so ops can see what
went out without digging through logs. SMS/WhatsApp/push are V2, out of scope.

## Data model (as-built)

```
Table: notification_logs                        (RLS enforced, app: apps.notifications)
  id                    uuid PK
  tenant_id             uuid              (RLS)
  notification_type     welcome | trial_expiry_reminder | invoice_issued | payment_receipt
  recipient_email        email, blank (blank only when status=skipped)
  subject                varchar(255), blank
  status                 sent | failed | skipped
  reference              varchar(255), blank, indexed
                          — 'user:<uuid>' | 'invoice:<uuid>' | 'payment:<uuid>'
                          | 'tenant_trial:<uuid>:<days_before>'
                          also doubles as the trial-reminder idempotency key
  note                   text, blank            (error message, or why skipped)
  sent_at                datetime, null
  created_at / updated_at

Table: platform_config  (Module 01, extended here)
  trial_reminder_first_days_before   positive int, default 15
  trial_reminder_second_days_before  positive int, default 5
  # invariant 10: offsets from trial_ends_at, not absolute "Day 45/55" — stays
  # correct if a Super Admin edits trial_days.
```
No new tables for Plan/Subscription/Invoice/Payment/Tenant — this module only
adds the audit table above and two config fields.

## API endpoints
```
(none)
```
PRD Module 18 doesn't specify a UI/API for viewing notification history —
`NotificationLog` is visible via Django admin only (read-only, no add/change).
See Decisions.

## Business rules (each maps to a test)
1. Signup dispatches the existing verification email (`apps.accounts.emails.
   send_verification_email`, unchanged) via a Celery task
   (`apps.accounts.tasks.send_welcome_email_task`), deferred with
   `transaction.on_commit` so the task never runs before the User row is
   committed. The task logs one `NotificationLog(type=welcome)` row — no
   second email is sent (see Decisions).
2. Issuing an invoice (`InvoiceViewSet.issue`, not the draft `create`) emails
   the resident and logs `NotificationLog(type=invoice_issued,
   reference='invoice:<id>')`. Draft creation/edits do not notify — a draft
   isn't yet a real obligation.
3. Recording a payment (`services.record_payment`) emails a receipt to the
   resident and logs `NotificationLog(type=payment_receipt,
   reference='payment:<id>')`.
4. A resident with no `email` on file is `skipped` (not `failed`) — fail-open,
   same discipline as Module 13's plan limits. `note` explains why.
5. A broken SMTP server logs `status=failed` with the exception message in
   `note`; it never raises back into the request/task that triggered it (an
   invoice-issue or payment-record action must succeed even if the mailer is
   down).
6. Trial-expiry reminders are a daily sweep
   (`send_trial_expiry_reminders` management command ->
   `services.due_trial_reminders()` -> one Celery task dispatch per due
   tenant). A tenant is due when `trial_ends_at.date() - today` equals either
   configured offset (`PlatformConfig.trial_reminder_first_days_before` /
   `..._second_days_before`) and only while `Tenant.status == TRIAL`.
7. Trial reminders are idempotent: the task checks for an existing
   `NotificationLog` with the same `reference` (`tenant_trial:<tenant>:
   <offset>`) before sending, so running the sweep twice in one day (or a
   retry) never double-sends.
8. The trial-reminder email goes to the tenant's Owner (earliest-created
   `Owner` user on that tenant), in that user's `language_code` (invariant 7 —
   all four notification bodies go through gettext).
9. All four Celery tasks fetch their subject row (`Invoice`/`Payment`, both
   RLS-enforced) under a super-admin tenant context first (task start has no
   tenant context — same pattern as Module 13's webhook handler), then do the
   actual send/log under the row's real `tenant_id` so the
   `NotificationLog` insert passes RLS's `WITH CHECK`.
10. `notification_logs` is RLS-enforced; isolation proven the same way as
    other modules.

## Permissions
No new permission — no API surface. `NotificationLog` is Django-admin-only
(superuser login), matching how `SubscriptionPayment` is surfaced in Module 13.

## Edge cases handled
- Signup does not send two emails ("welcome" + "verify your email") — the
  verification email already opens with "Welcome, `<name>`!"; a `welcome`
  `NotificationLog` row is recorded without a duplicate send.
- A tenant whose `trial_reminder_first_days_before` and `..._second_days_before`
  happen to be set equal by a Super Admin fires both (they dedupe separately by
  `reference`, so this doesn't double-send for one offset).
- Running `send_trial_expiry_reminders` after a tenant has left `TRIAL` status
  (upgraded, suspended, cancelled) sends nothing further for that tenant.
- Celery tasks run `CELERY_TASK_ALWAYS_EAGER=True` in dev/test (`config/
  settings/dev.py`) so `manage.py test` and local runs need no separate worker
  process; production (`prod.py`) requires the real `celery` worker (already
  in `docker-compose.yml`).

## Open questions / Decisions
- [DECISION 2026-07-04] **Welcome email == verification email.** PRD Module
  18 lists "Welcome email on signup" as a separate MVP bullet, but the
  existing verification email (Module 01) already opens with "Welcome,
  `<name>`!" and carries the activation link. Sending a second, purely
  ceremonial "Welcome!" email to a brand-new signup was judged worse UX than
  reusing the one email everyone already gets. `apps.accounts.tasks.
  send_welcome_email_task` sends the (unchanged) verification email and
  records a `NotificationLog(type=welcome)` entry — honest logging of what
  actually happened, no fabricated second send.
- [DECISION 2026-07-04] **Welcome task lives in `apps.accounts`, not
  `apps.notifications`.** It needs `User`/token logic that
  `apps.accounts.emails` already owns; putting the task in `apps.notifications`
  would force that module to import `apps.accounts` at module top while
  `apps.accounts` also needs to import the task — a circular import. All
  other Module 14 tasks (invoice, payment, trial reminder) live in
  `apps.notifications.tasks` and lazy-import the models they need
  (`apps.billing.Invoice/Payment`, `apps.accounts.Tenant`) *inside* the task
  function body, not at module top, for the same reason — `apps.billing`
  imports `apps.notifications.tasks` at its call sites, so the reverse import
  must never happen at load time.
- [DECISION 2026-07-04] **Invoice-issued notification fires on `issue`, not
  `create`.** A draft invoice is an internal working document (Module 08); the
  resident has nothing to see or owe until it's issued. PRD's "Invoice
  generated notification" is interpreted as "the resident's invoice is now
  real," matching `issue_date`/obligation semantics elsewhere in the spec.
- [DECISION 2026-07-04] **Trial-reminder offsets are config, not the PRD's
  literal "Day 45/55".** Those numbers only make sense for the PRD's example
  60-day trial. `PlatformConfig.trial_reminder_first/second_days_before`
  (defaults 15/5 — i.e. Day 45/55 of a 60-day trial) express the same
  schedule as *days before expiry*, so a Super Admin changing `trial_days`
  doesn't silently break the reminder schedule (invariant 10).
- [DECISION 2026-07-04] **No dedicated notification-history API.** PRD Module
  18 doesn't specify one, and no permission in the PRD §6 matrix maps
  cleanly onto "view sent notifications." `NotificationLog` is Django-
  admin-only (read-only) for now — same treatment Module 13 gave
  `SubscriptionPayment`. Revisit if Owners ask to see their own notification
  history in-app.
- [DECISION 2026-07-04] **`transaction.on_commit` everywhere a task is
  dispatched after a DB write** (signup, invoice issue, payment record) —
  without it, a Celery worker (running in a separate process, no shared
  transaction) could look up a row before the write that created/changed it
  is actually visible, since `.delay()` enqueues immediately regardless of
  whether the enclosing transaction later commits or rolls back.
- [DECISION 2026-07-04] **`send_trial_expiry_reminders` is a management
  command, not a Celery beat schedule** — same reasoning as Module 13's
  `check_subscription_grace_periods` (no `django-celery-beat` dependency
  added yet); run via cron or a manual ops trigger.
- [OPEN] Password-reset and staff-invite emails (`apps.accounts.emails`)
  stay synchronous — outside this module's literal MVP scope (welcome/trial/
  invoice/receipt). Revisit moving them onto Celery + `NotificationLog`
  together if/when notification history needs to cover the full auth-email
  surface.
- [BUG FIXED 2026-07-04] The `celery` Docker service was crash-looping
  (`ModuleNotFoundError: No module named 'django_extensions'`) — its image
  was stale from before Module 13's `docker compose build backend` (which
  only rebuilt `backend`, not `celery`). This module is the first to
  actually exercise Celery tasks, which surfaced it. Fixed with
  `docker compose build celery` + recreate; unrelated to this module's code.

## Changelog
- 2026-06-xx  Created stub.
- 2026-07-04  Built: `NotificationLog` model (RLS), two `PlatformConfig`
  trial-reminder-offset fields, `apps.notifications.{emails,services,tasks}`,
  a Celery task per notification (welcome lives in `apps.accounts.tasks`),
  the `send_trial_expiry_reminders` management command, hooks in
  `SignupSerializer.create`, `InvoiceViewSet.issue`, and
  `billing.services.record_payment`. `CELERY_TASK_ALWAYS_EAGER` enabled in
  `config/settings/dev.py`. 11 new tests (welcome, invoice-issued incl. no-
  email skip, payment receipt, trial-reminder offsets/idempotency/non-trial
  exclusion, isolation) + 2 existing `apps.accounts` signup tests updated for
  the async dispatch (`captureOnCommitCallbacks`). Full suite (369) green.
  Also fixed a stale `celery` Docker image (see Decisions).
