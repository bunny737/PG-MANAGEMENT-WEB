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

**Two pricing types as of 2026-08-11** (owner decision — Google-Workspace-
style per-bed billing, pulled forward from a later phase): `FLAT_MONTHLY` is
the original fixed-tier-price-in-advance flow above, unchanged. `PER_BED_
MONTHLY` bills a tenant's provisioned bed count against a Super-Admin-
configured marginal tier ladder (`PlanBedTier` — free allowance, then a
per-bed rate, cheaper above a volume threshold), **in arrears**: a daily
command closes each tenant's billing cycle, prices it from a bed-day ledger,
and issues a Razorpay Invoice for one payment per month. See Decisions below
for why arrears billing needed a different Razorpay primitive entirely.

## Data model (as-built)

```
Table: plans                                    (NOT under RLS — platform catalog, like PlatformConfig)
  id                    uuid PK
  name                  varchar(100), unique     (free text — PRD: "will be finalised based on market feedback")
  pricing_type          flat_monthly | per_bed_monthly, default flat_monthly
  max_properties        int, null                (null = Unlimited; PER_BED_MONTHLY plans must be null — no cap, usage-based)
  max_residents_per_property  int, null           (null = Unlimited; same PER_BED_MONTHLY constraint)
  price_per_month       decimal(10,2), null       (null for PER_BED_MONTHLY — see plan_bed_tiers)
  is_trial_plan         bool, default False       (which plan's limits a trial tenant borrows)
  is_active             bool, default True        (retire without deleting)
  razorpay_plan_id       varchar(100), blank       (lazily created on first select_plan; FLAT_MONTHLY only)
  created_at / updated_at

Table: plan_bed_tiers                           (NOT under RLS — child of plans, same platform-catalog status)
  id                    uuid PK
  plan                  FK -> plans (CASCADE)
  up_to_beds            int, null                (null = open-ended top tier; exactly one per plan)
  rate_per_bed          decimal(12,2)
  unique(plan, up_to_beds)                        (ordering: up_to_beds ASC NULLS LAST)

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
  amount                decimal(10,2)     (the amount Razorpay actually charged — read from the
                                            webhook payload, not plan.price_per_month; see Decisions)
  status                success | failed
  paid_at               datetime, null
  raw_payload           jsonb, default {}   (the full webhook body, for audit/debugging)
  created_at / updated_at

Table: bed_ledger_entries                       (RLS enforced, app: apps.subscriptions)
  id                    uuid PK
  tenant_id             uuid              (RLS)
  bed_id                uuid              (plain UUID, not FK — the bed may since have been hard-deleted)
  event                 added | removed
  occurred_at           datetime
  index(tenant_id, occurred_at)
  -- Append-only. Fed by post_save/post_delete signals on properties.Bed
  -- (apps/subscriptions/signals.py, wired in AppConfig.ready()), not by
  -- editing apps.properties — see Decisions for why a ledger exists at all.

Table: subscription_invoices                    (RLS enforced, app: apps.subscriptions)
  id                    uuid PK
  tenant_id             uuid              (RLS)
  subscription          FK -> subscriptions (PROTECT)
  period_start / period_end   date
  status                draft | issued | paid | failed
  total_amount          decimal(12,2)
  billed_bed_count_start / billed_bed_count_end   int
  razorpay_invoice_id   varchar(100), blank
  issued_at / paid_at   datetime, null
  unique(subscription, period_start)              (idempotency — a re-run of the daily
                                                     command can't double-invoice a cycle)

Table: subscription_invoice_lines               (RLS enforced, app: apps.subscriptions)
  id                    uuid PK
  tenant_id             uuid              (RLS)
  invoice               FK -> subscription_invoices (CASCADE)
  description            varchar(255)      (e.g. "250 beds @ ₹2.00 (2026-08-01–2026-08-16)")
  quantity               decimal(12,4)
  unit_rate              decimal(12,4)
  amount                 decimal(12,2)
  addons                 jsonb, default []  (reserved, empty in MVP — invariant 6)
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
GET         /api/v1/subscriptions/{tenant_id}/price-preview/  live PER_BED_MONTHLY breakdown at today's bed count   manage_subscription
GET         /api/v1/subscriptions/{tenant_id}/invoices/       PER_BED_MONTHLY billing history            manage_subscription
POST        /api/v1/subscriptions/webhook/               Razorpay webhook receiver (subscription.* AND invoice.* events)   public (HMAC-verified)
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
14. **Billable bed count = every `Bed` row under the tenant** (provisioned
    capacity, not occupancy — owner decision, matches Google Workspace's
    per-provisioned-seat model; excluding e.g. `maintenance` beds would be
    an easy way to game the bill). `services.get_total_beds`.
15. **PER_BED_MONTHLY pricing is a marginal tier ladder, applied like income
    tax brackets** (`pricing.monthly_charge`): each bed is charged at the
    rate of the tier it falls into, tiers below it having already been
    filled. A free allowance and a volume discount are the *same*
    mechanism — one ordered list of `(up_to_beds, rate_per_bed)` steps —
    not two competing discount modes (see Decisions for why this beats a
    flat percentage-off discount).
16. **Mid-cycle bed changes are billed by proration, not averaging**
    (`pricing.prorated_charge` + `pricing.bed_segments`): the cycle is split
    into constant-bed-count segments from the `bed_ledger_entries` history,
    each segment priced at its own bed count's full-cycle rate and scaled
    by the fraction of the cycle it covers, then summed and rounded once
    (`ROUND_HALF_UP`, never per-segment).
17. **Invoice generation is arrears, daily-swept, and idempotent**
    (`generate_subscription_invoices` management command →
    `services.generate_invoice_for_subscription`): any `PER_BED_MONTHLY`
    subscription whose `current_period_end` has passed gets a
    `SubscriptionInvoice` (one line per tier crossed per segment) and
    advances to the next calendar-month cycle
    (`pricing.next_cycle_end` — 28/29/30/31-day aware, not
    `timedelta(days=30)`) regardless of payment outcome. Re-running the
    command is a no-op for any cycle already invoiced
    (`unique_invoice_per_cycle`).
18. **A cycle below `PlatformConfig.min_billable_amount` is marked paid
    with no Razorpay call at all** — a tenant fully inside the free
    allowance never touches the payment gateway.
19. **PER_BED_MONTHLY activates the tenant on plan selection, not on a
    webhook-confirmed charge** (see Decisions) — the opposite of rule 5,
    which still governs FLAT_MONTHLY.
20. **The webhook handles two independent event families** now: `invoice.*`
    (arrears, keyed by `razorpay_invoice_id` on `SubscriptionInvoice`) and
    everything else, i.e. `subscription.*`/`payment.failed` (advance,
    keyed by `razorpay_subscription_id`, as in rule 6). Both branches are
    idempotent on `razorpay_payment_id` — a replayed webhook can no longer
    create a duplicate `SubscriptionPayment` (this was a pre-existing gap,
    fixed in the same change that added the second event family).

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
- `Bed.delete()` (`apps.properties.models.Bed`) is a hard delete — there is
  no soft-delete anywhere in `apps.properties`. Bed-day proration is
  impossible to reconstruct from the live `beds` table once a bed is gone,
  which is why `bed_ledger_entries` exists as an append-only log fed by
  signals, rather than counting `Bed.objects.filter(...)` at invoice time.
- The `Bed` ledger signals live in `apps.subscriptions.signals`, wired up in
  `SubscriptionsConfig.ready()` — not in `apps.properties` — specifically so
  Module 02 stays untouched by this module's billing concern. `bulk_create`/
  `bulk_delete` on `Bed` would bypass these signals (Django signals only
  fire on individual `save()`/`delete()`); no code path in the app does
  that today, but a reconciliation check (comparing the live bed count to
  the ledger's derived count) would be needed before relying on bulk bed
  operations anywhere.

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
  history and invoices from platform" per PRD Module 20): `FLAT_MONTHLY`
  is still covered only by `SubscriptionPayment` raw records.
  `PER_BED_MONTHLY` now has a real itemized `SubscriptionInvoice` (this
  change) — but a formatted, downloadable PDF/receipt view of it is still
  deferred to Module 17 (Export) alongside resident-facing invoice PDFs.
- [OPEN] Data retention on `cancelled` (PRD: "data retained 30 days before
  permanent deletion") has no automated purge job yet — out of scope until
  a module explicitly owns tenant data deletion.
- [DECISION 2026-08-11] **Per-bed pricing is additive, not a replacement,
  and is a genuine amendment to PRD §4.** PRD §4 specifies flat-tier
  pricing on properties + active-residents-per-property (₹199/499/999/
  2499) — Module 13 was built exactly to that spec, and it still is:
  `pricing_type` defaults to `FLAT_MONTHLY`, so every existing `Plan` row,
  live `Subscription`, and Razorpay mandate is untouched. `PER_BED_MONTHLY`
  is a second, opt-in pricing scheme a Super Admin can choose per plan.
  Flagging here because a spec/PRD reader should not assume the two
  co-existing pricing models were always the plan — see the PRD amendment
  in `docs/pg_hostel_management_prd_v2.md` §4.
- [DECISION 2026-08-11] **Arrears billing, prorated by bed-day, not advance
  billing.** Owner requirement: beds addable any time; an invoice is
  generated once the cycle closes, prorated for exactly how long each bed
  existed; one payment per month (Google Workspace's Flexible-plan model).
  This is the opposite of every existing FLAT_MONTHLY assumption in this
  module (fixed amount, charged in advance, confirmed by webhook before
  activation) — hence a second, parallel billing path rather than a
  branch inside the existing one.
- [DECISION 2026-08-11] **Pricing is one marginal tier ladder
  (`PlanBedTier`), not `rate_per_bed` + `discount_threshold_beds` +
  `discount_percentage` + `discount_rate_per_bed`.** A free allowance and a
  volume discount are the same mechanism. A flat percentage-off-above-
  threshold design has a real defect a tax-bracket-style ladder doesn't: at
  "20% off above 300 beds," a 300-bed tenant pays ₹600 and a 301-bed tenant
  pays ₹481.60 — adding a bed lowers the bill. The ladder is monotonic by
  construction (proven by `test_pricing.
  PricingEngineTests.test_boundary_is_monotonically_non_decreasing`) and
  satisfies invariant 6 (the engine iterates a list; a Super Admin changing
  the ladder needs zero code changes).
- [DECISION 2026-08-11] **Razorpay Add-ons are deprecated — arrears amounts
  are billed via the Razorpay Invoices API, not Subscriptions.** The
  natural design (keep the existing Subscriptions-API mandate, push each
  cycle's variable amount as an add-on) is unavailable: Razorpay's Add-ons
  feature is deprecated. Route taken instead: a Razorpay **Customer** is
  created per tenant (`razorpay_client.create_razorpay_customer`,
  lazily, same pattern as the existing lazy `Plan.razorpay_plan_id`
  creation), and each closed cycle creates+issues a Razorpay **Invoice**
  with one line item per `SubscriptionInvoiceLine`
  (`razorpay_client.create_razorpay_invoice`). `invoice.paid` /
  `invoice.expired` / `invoice.partially_paid` webhooks reconcile it. This
  also fixed a real pre-existing bug while touching the shared webhook
  code: `handle_webhook_event` recorded `SubscriptionPayment.amount` from
  `plan.price_per_month` instead of the amount Razorpay's payload actually
  charged — silently wrong for any adjusted/partial FLAT_MONTHLY payment.
  Also fixed: a replayed `subscription.charged`/`invoice.paid` webhook can
  no longer create a duplicate `SubscriptionPayment` (both handlers now
  check `razorpay_payment_id` first).
- [DECISION 2026-08-11] **PER_BED_MONTHLY activates the tenant on plan
  selection, not on a webhook-confirmed charge — the opposite of the
  2026-07-04 FLAT_MONTHLY decision above.** That decision's reasoning
  ("never mark a tenant active on the strength of a request that didn't
  actually charge a card") assumed advance billing, where a charge attempt
  happens immediately. Arrears billing has no charge to confirm until the
  cycle closes — weeks or a month later — so requiring a webhook first
  would leave every PER_BED_MONTHLY tenant stuck on `trial` for their
  entire first cycle. `FLAT_MONTHLY` keeps the original rule unchanged.
- [DECISION 2026-08-11] **`min_billable_amount` lives on `PlatformConfig`,
  not as a literal in `services.py`** (invariant 10) — a tenant whose
  cycle total falls under it is marked `paid` with a ₹0 invoice and never
  reaches Razorpay at all, avoiding a charge attempt below Razorpay's own
  practical minimum.
- [OPEN] The Razorpay Invoices integration above (customer creation,
  invoice creation, webhook event names/payload shape) is implemented
  against current public Razorpay documentation but has not been verified
  against a live Razorpay sandbox account — do that before enabling
  `PER_BED_MONTHLY` in any environment with real `RAZORPAY_KEY_ID`/
  `RAZORPAY_KEY_SECRET` configured. Locally/in CI it exercises the
  same "stub when unconfigured" path the rest of this module already relies
  on (`razorpay_client.is_configured()`).
- [DECISION 2026-09-10] **Webhook verification fails closed in production.**
  `verify_webhook_signature` previously returned `True` whenever
  `RAZORPAY_WEBHOOK_SECRET` was unset — the endpoint is public and
  unauthenticated, so a misconfigured prod would let anyone drive tenant
  status and platform payments. It now skips verification only when the new
  `RAZORPAY_ALLOW_UNSIGNED_WEBHOOKS` setting is on; `dev.py` sets it, `base`
  (prod) defaults it `False`. (Can't gate on `settings.DEBUG` — Django's test
  runner forces `DEBUG=False`.)
- [DECISION 2026-09-10] **Webhook handlers lock their subject row + partial-
  unique `razorpay_payment_id`.** Idempotency was an `.exists()`-then-
  `.create()` with no lock or constraint, so replayed / concurrent Razorpay
  deliveries could double-record a charge and double-transition status.
  `_handle_subscription_webhook` / `_handle_invoice_webhook` now
  `select_for_update(of=('self',))` the `Subscription` / `SubscriptionInvoice`
  at the top of the atomic block (also fixing a stale pre-lock `before_status`
  read), the failure branches gained the same `.exists()` guard the success
  branches had, and `SubscriptionPayment` has a
  `unique_razorpay_payment_id` constraint (partial, non-empty) as the backstop.
- [DECISION 2026-09-10] **Plan-limit checks row-lock the subscription.**
  `check_property_limit` / `check_resident_limit` were count-then-create races
  — parallel requests sailed past the PRD "hard block". Both now go through
  `_subscription_for_limit_check`, which `select_for_update(of=('self',))` the
  tenant's `Subscription` row when the caller is inside a transaction (degrades
  to an unlocked read otherwise). `PropertyViewSet.perform_create` and
  `ResidentViewSet.change_status` were wrapped in `transaction.atomic` so the
  lock is held through the insert; `AdmissionViewSet.perform_create` already
  was.

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
- 2026-08-11  Added `PER_BED_MONTHLY` as a second, opt-in pricing type
  (owner decision: Google-Workspace-style per-bed billing, arrears,
  prorated by bed-day) alongside the unchanged `FLAT_MONTHLY` flow: `Plan.
  pricing_type` + `PlanBedTier` (marginal tier ladder — free allowance,
  then per-bed rate, cheaper above a volume threshold, fully Super-Admin-
  configurable, zero hardcoded rates/thresholds); `apps.subscriptions.
  pricing` (pure Decimal engine — `monthly_charge`, `bed_segments`,
  `prorated_charge`, `next_cycle_end`); `BedLedgerEntry` (RLS, append-only,
  fed by `Bed` post_save/post_delete signals, backfilled for existing beds
  in the same migration) since `Bed.delete()` is a hard delete and bed-days
  can't otherwise be reconstructed; `SubscriptionInvoice`/
  `SubscriptionInvoiceLine` (RLS, list-of-line-items per invariant 6,
  idempotent per cycle) generated daily by `generate_subscription_invoices`
  (mirrors the existing grace-period command's not-Celery-beat pattern);
  Razorpay Invoices integration (`create_razorpay_customer`,
  `create_razorpay_invoice`) since Razorpay Add-ons are deprecated —
  Subscriptions-API add-ons were the original plan and aren't available;
  webhook handler split into `subscription.*` (advance) and `invoice.*`
  (arrears) branches, fixing two pre-existing bugs in the same pass
  (amount read from `plan.price_per_month` instead of the actual charged
  amount; no idempotency guard against a replayed webhook); `price-preview`
  and `invoices` API actions; `PlatformConfig.min_billable_amount`.
  Corrected `GlobalSettings.tsx`'s "Plan & Subscription" tab, which showed
  fabricated bed-pricing data (₹49/mo, "348/500 beds") wired to no API —
  replaced with an honest placeholder pending FE-13. PRD §4 amended to
  document both pricing models. 39 new backend tests (pricing engine
  incl. the monotonicity property a percentage-discount design would have
  failed, proration across tier boundaries and partial months, invoice
  generation + idempotency, RLS isolation for the three new tables); full
  subscriptions suite (90) green.
