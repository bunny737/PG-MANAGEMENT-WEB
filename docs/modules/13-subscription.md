# Module: Subscription + Razorpay + Plan Limits

> Keep this file in sync with the code AT ALL TIMES.
> If the code and this file disagree, this file is wrong — fix it in the same commit.

**Status:** Done
**Phase:** 3
**PRD reference:** Section 4 (Subscription & Pricing Model), Module 20 (Subscription Management)
**Depends on:** 01, 02
**Blocks:** none

## Purpose
Super Admin defines pricing tiers (Plan). Every tenant gets a Subscription
row from signup; while unconfigured, nothing is enforced (fail-open). Once
a Plan is attached (directly, or borrowed from the trial-default plan while
on trial), property/resident creation is hard-blocked at the configured
caps. Owner picks/changes a plan, which creates a Razorpay subscription;
a Razorpay webhook confirms the charge and drives the tenant's billing
status (`trial → active → payment_failed → suspended`/`cancelled`). Super
Admin can override a tenant's limits or manually suspend/reactivate.

## Data model (as-built)

```
Table: plans                                    (NOT under RLS — platform catalog, like PlatformConfig)
  id                    uuid PK
  name                  varchar(100), unique     (free text — PRD: "will be finalised based on market feedback")
  max_properties        int, null                (null = Unlimited)
  max_residents_per_property  int, null           (null = Unlimited)
  price_per_month       decimal(10,2)
  is_trial_plan         bool, default False       (which plan's limits a trial tenant borrows)
  is_active             bool, default True        (retire without deleting)
  razorpay_plan_id       varchar(100), blank       (lazily created on first select_plan)
  created_at / updated_at

Table: subscriptions                            (NOT under RLS — see Decisions)
  id                    uuid PK
  tenant                OneToOne -> accounts.Tenant (CASCADE)
  plan                  FK -> plans (PROTECT), null   (null = trial, no plan chosen)
  razorpay_subscription_id  varchar(100), blank
  razorpay_customer_id      varchar(100), blank
  current_period_start / current_period_end   date, null
  payment_failed_at     datetime, null          (start of the 5-day grace period)
  max_properties_override    int, null          (Super Admin manual override)
  max_residents_override     int, null
  created_at / updated_at

Table: subscription_payments                    (RLS enforced, app: apps.subscriptions)
  id                    uuid PK
  tenant_id             uuid              (RLS; stamped from subscription.tenant_id)
  subscription          FK -> subscriptions (PROTECT)
  razorpay_payment_id   varchar(100), blank
  amount                decimal(10,2)
  status                success | failed
  paid_at               datetime, null
  raw_payload           jsonb, default {}   (the full webhook body, for audit/debugging)
  created_at / updated_at
```

## API endpoints
```
GET|POST    /api/v1/plans/                              list (active-only for tenants) / create   manage_subscription (read) / Super Admin (write)
GET|PATCH|DELETE /api/v1/plans/{id}/                     retrieve/edit/retire (blocked if in use)   Super Admin
GET         /api/v1/subscriptions/{tenant_id}/           plan + usage summary                       manage_subscription
POST        /api/v1/subscriptions/{tenant_id}/select-plan/   pick/change plan (Razorpay subscription created)  manage_subscription
PATCH       /api/v1/subscriptions/{tenant_id}/override-limits/  manual per-tenant override           Super Admin
POST        /api/v1/subscriptions/{tenant_id}/suspend/        manual suspend                          Super Admin
POST        /api/v1/subscriptions/{tenant_id}/reactivate/     manual reactivate                        Super Admin
POST        /api/v1/subscriptions/webhook/               Razorpay webhook receiver                  public (HMAC-verified)
```
Looked up by **tenant id**, not the Subscription row's own id — the
frontend always reaches a tenant's subscription via
`/subscriptions/{tenant_id}/` with no separate "my subscription" step.

## Business rules (each maps to a test)
1. **Fail-open by default.** A tenant with no `Subscription` row, no `plan`
   (and no trial-default plan configured), or a plan with a `null` limit,
   has nothing enforced. Limits only bite once a Super Admin has actually
   configured a Plan — this is what keeps every pre-existing test in the
   whole suite green without modification.
2. **Property hard block** (`check_property_limit`, hooked into
   `PropertyViewSet.perform_create`): rejected (`property_limit_reached`)
   once the tenant's property count reaches `effective_max_properties()`.
3. **Resident hard block** (`check_resident_limit`, hooked into
   `AdmissionViewSet.perform_create` **and** `ResidentViewSet.change_status`
   when the transition newly counts): rejected (`resident_limit_reached`)
   once a *single property's* Active+Notice-Period resident count reaches
   `effective_max_residents_per_property()` — checked **per property**, not
   tenant-wide (PRD §4). `Active ↔ Notice Period` never re-checks since both
   already count toward the same total.
4. **Effective limits resolve in order:** Super Admin override (if set) →
   the tenant's own `plan` (if set) → the Super-Admin-flagged trial-default
   plan (only while `Tenant.status == TRIAL` and no plan is set) → `None`
   (unlimited).
5. **Select plan** (`POST .../select-plan/`) lazily creates the Razorpay
   plan (first tenant to pick it) and always creates a fresh Razorpay
   subscription, storing both ids. It does **not** itself flip the tenant
   to `active` — only a webhook-confirmed charge does (see Decisions).
6. **Webhook** (`POST /subscriptions/webhook/`) maps Razorpay events to
   tenant status: `subscription.activated`/`subscription.charged` → `active`
   (+ `SubscriptionPayment` success, period dates set, `payment_failed_at`
   cleared); `payment.failed` → `payment_failed` (+ `payment_failed_at` now,
   `SubscriptionPayment` failed); `subscription.halted` → `suspended`;
   `subscription.cancelled` → `cancelled`. An unknown subscription id or
   unhandled event type is a harmless no-op (still `200`, so Razorpay
   doesn't retry forever).
7. **Grace period** (`check_subscription_grace_periods` management command,
   calling `process_payment_grace_periods()`): any tenant `payment_failed`
   for longer than `PlatformConfig.payment_grace_days` (default 5) is
   suspended.
8. **Super Admin override** (`PATCH .../override-limits/`) is partial —
   omitting a field leaves it unchanged; explicit `null` clears it back to
   the plan's own limit.
9. **Manual suspend/reactivate** (Super Admin only): `suspend` rejects an
   already-suspended tenant (`already_suspended`); `reactivate` requires the
   tenant currently be `suspended` or `payment_failed`
   (`tenant_not_suspended`) and always lands on `active`.
10. A Plan with any `Subscription` referencing it cannot be deleted
    (`plan_in_use`) — retire it (`is_active=False`) instead.
11. Plan selection, override, suspend, reactivate, and every tenant status
    change (webhook- or command-driven) are audit logged.
12. `manage_subscription` (Super Admin, Owner) gates the tenant-facing
    endpoints; Owner is scoped to their own tenant only (cross-tenant →
    404), Super Admin can reach any tenant. Plan catalog writes and the
    override/suspend/reactivate actions are Super-Admin-only.
13. `subscription_payments` is RLS-enforced (isolation proven); `plans` and
    `subscriptions` are deliberately not (see Decisions).

## Permissions
- `manage_subscription` (Super Admin, Owner): view plans, view own
  subscription + usage, select/change plan.
- Super Admin only: create/edit/retire a Plan, override a tenant's limits,
  manually suspend/reactivate a tenant.
- Everyone else (Manager, Receptionist, Resident): no access.

## Edge cases handled
- `SubscriptionPayment.tenant_id` is stamped from `subscription.tenant_id`
  even though `Subscription` itself carries no RLS `tenant_id` column (see
  Decisions) — the webhook handler explicitly opens a `tenant_context()`
  block before writing, since the request that triggers it is unauthenticated
  and no middleware has set the Postgres GUCs for it.
- The webhook URL (`/subscriptions/webhook/`) is registered **before**
  `router.urls` in `urls.py` — otherwise the router's own
  `subscriptions/{tenant_id}/` detail pattern greedily matches
  `subscriptions/webhook/` first (`tenant_id='webhook'`) and 401s (found
  and fixed while building this module's tests).
- `razorpay==1.4.x` (already a locked dependency) imports the legacy
  `pkg_resources` API, which `setuptools>=81` removed outright — the import
  crashed on a fresh image. Pinned `setuptools<81` in
  `requirements/base.txt` to fix it; this is a real, necessary fix, not a
  workaround.

## Open questions / Decisions
- [DECISION 2026-07-04] **`Plan`/`Subscription` are NOT under
  `TenantModelMixin`/RLS.** A `tenant` FK on `Subscription` would collide
  with the mixin's own `tenant_id` RLS column (Django would raise a field
  clash — both want the `tenant_id` name). `Plan` is a platform catalog,
  not tenant data at all (same category as `PlatformConfig`). `Subscription`
  is tenant-identity/billing-account data — one row per tenant, and its
  access is always mediated through `request.user.tenant` or Super Admin,
  never row-level tenant context — the same architecture already used for
  `User` (see that model's own docstring: "Not under RLS... Views scope
  user queries at the app level instead"). `SubscriptionPayment` (a normal
  RLS-scoped list of records) is the one table in this module that *is*
  RLS-enforced, referencing `Subscription` by FK rather than `Tenant`
  directly so there's no naming clash.
- [DECISION 2026-07-04] **Selecting a plan doesn't itself activate the
  tenant.** PRD Module 20's lifecycle is explicit: "Day 60: Select Plan →
  Razorpay payment → Active subscription" — the payment step is what
  matters, and Razorpay's own subscription flow only confirms payment
  asynchronously via webhook. Modeling `select_plan` as "provisions the
  Razorpay subscription, frontend redirects to Razorpay Checkout, webhook
  confirms" avoids ever marking a tenant `active` on the strength of a
  request that didn't actually charge a card.
- [DECISION 2026-07-04] **Trial limits are borrowed from a Super-Admin-
  flagged "trial default" Plan (`is_trial_plan=True`), not hardcoded to a
  plan named "Starter".** The PRD lifecycle literally says the trial runs on
  "Starter plan features," but invariant 10 forbids hardcoding plan
  specifics — Super Admin flags whichever plan should apply during trial
  (normally the cheapest tier), and `Subscription.effective_plan()` borrows
  its limits only while `Tenant.status == TRIAL` and no plan has been
  explicitly selected yet.
- [DECISION 2026-07-04] **Fail-open, not fail-closed, when nothing is
  configured.** The alternative (block everything until a Plan exists)
  would have broken every single existing test across the whole codebase,
  since test tenants are created directly via `Tenant.objects.create(...)`
  and never carry a `Subscription`/`Plan`. Fail-open also matches the
  product reality: a fresh platform install with no plans configured yet
  shouldn't lock owners out of using the product at all.
- [DECISION 2026-07-04] **The existing "bare status flip" gap (Module 05/10)
  is closed specifically for the plan-limit case.** `ResidentViewSet.
  change_status` already let a resident skip Admission's own checks for
  minor workflow reasons (documented, accepted debt in earlier modules);
  a plan-limit bypass is the platform's core monetization control, so this
  module adds the same `check_resident_limit` call there too, but *only*
  when the transition would newly count the resident toward the cap.
- [DECISION 2026-07-04] **Trial-reminder emails (Day 45/55) and Day-60
  enforcement automation are deferred to Module 14 (Notifications).** No
  notification-delivery mechanism exists yet; this module only builds what
  doesn't depend on it — the actual status-transition/grace-period logic.
  A tenant whose trial lapses without selecting a plan is not automatically
  suspended today (PRD doesn't specify this transition explicitly); revisit
  once Module 14 exists to drive it.
- [DECISION 2026-07-04] **`check_subscription_grace_periods` is a plain
  management command, not a Celery beat schedule.** `django-celery-beat`
  isn't a project dependency and this is the first scheduled task in the
  codebase — adding periodic-task infrastructure un-asked was judged out of
  scope. The command is fully testable and ops can cron it (or Module 14
  can wire real beat scheduling when it adds its own periodic notification
  jobs).
- [DECISION 2026-07-04] Pinned `setuptools<81` (see Edge cases) — a real
  bug fix to the already-locked `razorpay` dependency, not a workaround.
- [OPEN] Billing history / invoice PDFs from the platform side ("Billing
  history and invoices from platform" per PRD Module 20) are covered by
  `SubscriptionPayment` as raw records; a formatted invoice/receipt view is
  deferred to Module 17 (Export) alongside resident-facing invoice PDFs.
- [OPEN] Data retention on `cancelled` (PRD: "data retained 30 days before
  permanent deletion") has no automated purge job yet — out of scope until
  a module explicitly owns tenant data deletion.

## Changelog
- 2026-06-xx  Created stub.
- 2026-07-04  Built: `Plan` (platform catalog) + `Subscription` (1:1 per
  tenant, deliberately outside RLS) + `SubscriptionPayment` (RLS) in
  `apps.subscriptions`. Plan-limit enforcement (`check_property_limit`,
  `check_resident_limit`) hooked into Module 02/04/05's existing
  create/status-change flows, fail-open when unconfigured. Razorpay
  integration (`razorpay_client.py`, stubbed locally when unconfigured):
  plan/subscription creation, webhook signature verification, and a webhook
  receiver driving the Tenant status lifecycle. Super Admin plan CRUD,
  per-tenant limit override, manual suspend/reactivate. Payment-failure
  grace-period sweep via a management command. Fixed a real `pkg_resources`/
  `setuptools` import bug in the already-locked `razorpay` dependency along
  the way. 51 new tests (plan CRUD, usage summary, property/resident limit
  enforcement incl. override/unlimited/trial-borrowed/per-property scoping,
  select-plan, webhook event handling, admin actions, grace-period command,
  RLS isolation); full suite (358) green. Spec written to as-built.
