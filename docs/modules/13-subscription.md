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
  max_beds              int, null                (null = Unlimited; total provisioned beds across the tenant;
                                                  PER_BED_MONTHLY plans must be null)
  price_per_month       decimal(10,2), null       (null for PER_BED_MONTHLY — see plan_bed_tiers)
  is_trial_plan         bool, default False       (which plan's limits a trial tenant borrows;
                                                  partial unique constraint single_trial_plan: at most one True)
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
  razorpay_subscription_id  varchar(100), blank   (the CURRENT paid subscription; webhooks look it up)
  pending_plan          FK -> plans (PROTECT), null (a flat plan chosen but not yet paid; limits don't use it)
  pending_razorpay_subscription_id  varchar(100), blank  (promoted into the two fields above on first charge — rule 26)
  razorpay_customer_id      varchar(100), blank
  current_period_start / current_period_end   date, null
  payment_failed_at     datetime, null          (start of the 5-day grace period)
  max_properties_override    int, null          (Super Admin manual override)
  max_residents_override     int, null
  max_beds_override          int, null
  created_at / updated_at

Table: razorpay_subscriptions                   (NOT under RLS, like subscriptions — the webhook reading it is unauthenticated)
  id                    uuid PK
  subscription          FK -> subscriptions (CASCADE)
  plan                  FK -> plans (PROTECT)
  razorpay_subscription_id  varchar(100), UNIQUE
  state                 pending | current | replaced | abandoned | cancelling | cancelled   (see rule 27)
  cancel_from           varchar(10), blank   (REPLACED/ABANDONED: where a failed cancel returns to)
  cancel_attempts int · last_cancel_error text · last_cancel_attempt_at · cancelled_at
  index(state)
  -- Every Razorpay subscription we create. subscriptions.razorpay_subscription_id /
  -- pending_* remain as "which is live / which is newest"; this is the reconciliation record.

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
GET         /api/v1/subscriptions/{tenant_id}/           plan + usage summary (+ razorpay_key_id, the public key Checkout needs; blank when Razorpay isn't configured)   manage_subscription
POST        /api/v1/subscriptions/{tenant_id}/select-plan/   pick/change plan (Razorpay subscription created)  manage_subscription
PATCH       /api/v1/subscriptions/{tenant_id}/override-limits/  manual per-tenant override           Super Admin
POST        /api/v1/subscriptions/{tenant_id}/suspend/        manual suspend                          Super Admin
POST        /api/v1/subscriptions/{tenant_id}/reactivate/     manual reactivate                        Super Admin
GET         /api/v1/subscriptions/{tenant_id}/price-preview/  live PER_BED_MONTHLY breakdown at today's bed count   manage_subscription
GET         /api/v1/subscriptions/{tenant_id}/invoices/       PER_BED_MONTHLY billing history            manage_subscription
POST        /api/v1/subscriptions/webhook/               Razorpay webhook receiver (subscription.* AND invoice.* events)   public (HMAC-verified)
GET         /api/v1/public/plans/                        anonymous plan catalogue for the marketing site (see "Public plan catalogue")   public (AllowAny, GET-only, throttled `public_catalog` 120/min, `Cache-Control: public, max-age=300`)
```

### Public plan catalogue
`GET /public/plans/` → `{currency, trial_days, updated_at, plans: [...]}`.
- `currency` is `razorpay_client.PLATFORM_CURRENCY` (the same constant Razorpay calls use); `trial_days` is read from `PlatformConfig` on every request (invariant 10); `updated_at` is the newest `updated_at` among the active plans and the config row (`null` when neither exists).
- Each plan is an **allow-list** (`PublicPlanSerializer`, not a subclass of `PlanSerializer`): `id, name, pricing_type, price_per_month, max_beds, bed_tiers[{up_to_beds, rate_per_bed}], is_trial_plan`. Razorpay ids, subscriber counts, property/resident caps and admin flags are never exposed.
- Active plans only; both pricing types are served (per-bed plans carry their tier ladder, `price_per_month` is `null`).
- Platform data only — no tenant data (test: response is byte-identical with and without tenants/subscriptions). Read-only: a public GET never creates the `PlatformConfig` row. Exempt from the app-client update/maintenance gate like `/support/`.
- Consumer: the marketing site's `/pricing` page, which has **no static fallback** — it serves the last good response, else "pricing temporarily unavailable".
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
   plan (first tenant to pick it) and a fresh Razorpay subscription, and
   records them as **`pending_plan` / `pending_razorpay_subscription_id`**.
   The tenant's `plan`, its limits and `razorpay_subscription_id` do not move,
   and the tenant is not flipped to `active` — only a webhook-confirmed charge
   on the pending subscription does all of that (rule 26). Choosing the plan
   an `active` tenant is already on is `plan_unchanged`.
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
10. A **locked** plan (it has a `razorpay_plan_id` or any `Subscription`
    referencing it) and the trial plan cannot be deleted (`plan_in_use`; the
    admin hides delete and bulk delete for them) — retire it
    (`is_active=False`) instead. See rule 23.
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
21. **Bed hard block** (`check_bed_limit`, hooked into
    `BedViewSet.perform_create` and `RoomViewSet.perform_create` when
    `auto_create_beds` is set, which checks `adding=sharing_type` so a room
    is created with all its beds or not at all): rejected
    (`bed_limit_reached`) once the tenant's total `Bed` count (provisioned,
    not occupied — rule 14's basis) would exceed `effective_max_beds()`.
    Resolves like rule 4 (override → plan → trial plan → unlimited).
    `max_beds` applies to FLAT_MONTHLY plans only; a PER_BED_MONTHLY plan
    must leave it null.
22. **Plan selection checks beds first.** `select_plan` re-reads the
    subscription under the same row lock the limit checks take, and rejects a
    plan whose `max_beds` is below the tenant's current bed count
    (`plan_bed_limit_exceeded`) **before any Razorpay call**. This is an
    up-front refusal, not the enforcement point: a flat plan only takes effect
    at payment (rule 26), by which time the tenant may have grown past the cap.
    That is accepted (rule 26), and `check_bed_limit` then simply blocks
    further beds.
23. **A locked plan's pricing is frozen.** Once a plan has a
    `razorpay_plan_id` or any subscriber, `price_per_month`, `pricing_type`
    and (for per-bed plans) its `PlanBedTier` rows reject changes
    (`plan_pricing_locked`; both the admin tier inline **and** the standalone
    `PlanBedTierAdmin` turn read-only and lose bulk delete, since deletes skip
    `clean()` and dropping the open-ended tier breaks pricing for every tenant
    on the plan). To reprice, create a new plan and retire the old one.
    `max_beds`, `name` and `is_active` stay editable.
    The plan API also enforces the pricing invariants `Plan.clean()` holds for
    the admin (`validate_pricing_invariants`: flat needs a price and no tiers;
    per-bed can't cap properties/residents/beds), because DRF never calls
    `clean()` — a capped per-bed plan is `plan_per_bed_capped`.
    Plan create/update/delete run in a transaction that **locks the Plan row
    first**, as does `select_plan` after locking the Subscription, so a
    reprice can't land between "no subscribers" and a tenant picking the plan
    (the Razorpay plan would keep the old price). Lock order is always
    Subscription → Plan; `PlanRepriceRaceTests` fails without the plan lock.
    The Django admin takes the same lock: `PlanAdmin.get_object` and
    `PlanBedTierAdmin.get_object` lock the parent Plan and then re-read, so form
    validation and save both run under it, and `PlanBedTierAdmin.save_model`
    re-checks a tier's target plan before writing (adding a tier has no object to
    lock earlier). `razorpay_plan_id` is read-only there: it is set by
    `select_plan`, and an editable copy would let a form opened before a tenant
    picked the plan blank the link on an unrelated save
    (`AdminRepriceRaceTests`).
24. **Exactly one trial plan.** Saving a plan with `is_trial_plan=True` moves
    the flag off every other plan in the same transaction; the current trial
    plan can't be un-flagged or retired (`trial_plan_required`) — hand the
    flag to another plan first. `single_trial_plan` is the database backstop.
25. **Launch lineup (data, seeded by migration 0006):** Basic — flat ₹149/month,
    `max_beds=500`, the trial plan; Unlimited — flat ₹249/month,
    `max_beds=null`. Properties and residents are uncapped on both. The trial
    is 45 days (`PlatformConfig.trial_days`).
26. **A flat plan change is pending until paid, then promoted.** The first
    `subscription.activated`/`charged` webhook on a pending Razorpay
    subscription (`_promote_ledger_row`, under the Subscription lock) makes its
    plan the tenant's `plan`, moves its id to `razorpay_subscription_id`,
    activates the tenant as in rule 6, audits `subscription.plan_changed`, and
    queues the subscription it replaces for cancellation (rule 27). If the
    tenant outgrew the new plan's bed cap in the meantime it is still applied
    (they paid; beds are never removed) and audited as
    `subscription.promoted_over_bed_limit`.
27. **Every Razorpay subscription is tracked in `razorpay_subscriptions` until it
    is terminal, so nothing is ever ignored as "unknown" and no cancellation is
    ever forgotten.** Webhooks are asynchronous, so these orderings are expected:
    - *A payment lands on a choice the tenant has since superseded* (ABANDONED):
      it is **honoured** — they paid for that plan, so it is promoted exactly as
      above. The newest choice stays pending and can still be paid; whichever is
      paid last wins, each payment replacing the previous live subscription.
    - *A charge lands on a subscription we already replaced* (REPLACED — a renewal
      that raced the cancel): the plan does not change. The charge is recorded as a
      `SubscriptionPayment` and audited `subscription.payment_needs_refund`
      (once, replays included) for ops to refund; **refunds are not automated.**
    - *`cancelled`/`halted` for a non-live subscription* confirms it finished
      (row → CANCELLED) and never touches the tenant's status; `payment.failed`
      on one is ignored. Only the live subscription drives status (rule 6).
    **A subscription being cancelled can't be promoted.** A cancelled Razorpay
    subscription never restarts, and the worker calls Razorpay with no database lock
    held, so it first *claims* the row with one conditional UPDATE to CANCELLING
    (`_claim_for_cancel`, `cancel_from` remembers where it came from). Webhooks only
    promote PENDING/ABANDONED rows, so the claim decides the race: a payment that
    arrives before the claim promotes the row and the worker stands down; one that
    arrives after is recorded and flagged `subscription.payment_needs_refund`, never
    promoted. The final update must find the row still CANCELLING; if the ledger has
    changed otherwise it is a conflict (audited `subscription.cancel_conflict`,
    reported as failed), not a success. A claim whose worker died is taken over after
    15 minutes. **A payment id is decided once.** A charge whose `razorpay_payment_id`
    is already recorded is a replay and changes nothing — checked before any promotion,
    so a payment flagged for refund under a claim cannot promote the row when a failed
    cancel later returns it to ABANDONED and Razorpay redelivers the webhook.
    **Cancellation is a retried queue, not a one-shot.** Replacing or abandoning a
    subscription marks its row REPLACED/ABANDONED in the same transaction as the
    plan change; `process_razorpay_cancellations` then runs right after commit and
    every 10 minutes (`retry_razorpay_cancellations`, a django-celery-beat task
    seeded by migration 0010, retimeable in admin) until Razorpay confirms. A cancel
    that errors is treated as done if Razorpay reports the subscription
    cancelled/completed/expired; otherwise `cancel_attempts` / `last_cancel_error`
    are updated and it stays queued (audited as `subscription.razorpay_cancel_failed`
    on the 1st, 10th and 50th failed attempt only). Nothing remote is ever done
    *before* the local writes — a cancel can't be rolled back if a later local
    write fails — so switching to a per-bed plan writes locally first and cancels
    the old flat subscription afterwards; during an outage the tenant is on the
    new plan while the old one is still being cancelled.

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
- [DECISION 2026-10-18] **Bed cap on flat plans.** Owner asked for a ₹149/month
  Basic plan up to 500 beds and a ₹249/month Unlimited plan above that, with
  beds as the only limit. New `Plan.max_beds` / `Subscription.max_beds_override`,
  enforced by `check_bed_limit` at both bed-creation sites. It counts
  provisioned beds (rule 14's basis), not occupied ones, so the cap and a
  per-bed bill agree on what a "bed" is. A cap on PER_BED_MONTHLY plans is
  rejected: usage-based billing stays uncapped.
- [DECISION 2026-10-18] **The limit-check lock is now join-free.**
  `_subscription_for_limit_check` used `select_for_update(of=('self',))` with
  `select_related('plan', 'tenant')`. When the lock waits on a concurrent plan
  change, PostgreSQL re-checks only the locked row, so the already-fetched plan
  could be pre-commit and a limit check could pass against stale limits. It
  now locks the bare subscription row and loads plan/tenant afterwards. Covers
  the property/resident checks too. Verified by removing the lock and watching
  `test_bed_limit_concurrency` fail.
- [DECISION 2026-10-18] **Downgrades are checked against current beds, under
  the lock.** Without that, "plan allows 500" could be defeated by selecting
  Basic while a tenant holds 600 beds, or by racing a bed create against the
  switch. The check runs before any Razorpay call so a refused switch has no
  external side effects.
- [DECISION 2026-10-18] **Live plans are immutable in price; they are retired,
  not edited or deleted.** Razorpay can't reprice an existing plan, and
  `select_plan` only creates the Razorpay plan when `razorpay_plan_id` is empty,
  so editing `price_per_month` afterwards would make the database show one
  price while customers pay another. "Locked" means a Razorpay ID **or** any
  subscriber (per-bed plans never get a Razorpay ID). The admin and API both
  enforce it; tier-inline deletes skip `clean()`, so admin *permissions* are what
  block them, and bulk delete is removed. `max_beds`, `name` and `is_active`
  stay editable: they're entitlements/labels, not what Razorpay charges.
- [DECISION 2026-10-18] **One trial plan, always.** The flag moves on save, the
  current trial plan can't be cleared or retired, and a partial unique
  constraint backs it. Without that, an admin un-flagging Basic would silently
  make every trial tenant unlimited (`effective_plan()` returns `None`). The
  one remaining path to "none" is faking the seed migration. The DRF serializer
  drops the auto-generated uniqueness validator for `is_trial_plan` because
  hand-over, not rejection, is the intended behaviour; plan-protection errors
  are raised from the viewset (a serializer `validate()` loses the error code).
- [DECISION 2026-10-18] **Seed migration 0006 is strict and one-way.** Fixed UUIDs
  for Basic/Unlimited; a re-run accepts rows that match exactly, and aborts
  with a clear message on a UUID holding other data or a different plan using
  the name — it never overwrites or merges. Reverse is a no-op: deleting plans
  would fail once tenants subscribe (PROTECT), and restoring `trial_days`
  would clobber later Super Admin edits. The trial changes 60 → 45 days (owner
  decision; the PRD still says 60). Existing tenants keep their `trial_ends_at`.
- [DECISION 2026-10-18] **Frontend room creation is atomic.** `AddRoomForm`
  created the room, then one `POST /beds/` per bed in parallel; near the cap
  that could leave a room with only some of its beds. It now sends
  `auto_create_beds: true` and reads the beds from the response.

- [DECISION 2026-10-18] **The owner plan screen (FE-13, partial) pays through
  Razorpay Checkout using a key id served by the API.** `SubscriptionSerializer`
  gained `razorpay_key_id` (the *public* key id, blank unless both Razorpay
  credentials are configured) instead of a `NEXT_PUBLIC_*` env var, so the
  browser can't be configured with a key from a different Razorpay account than
  the one that created the subscription. After selecting a flat plan the UI
  opens Checkout for `pending_razorpay_subscription_id`, then polls the
  subscription (6 × 2 s) and reports success only once `plan` is the plan it
  waited for and `pending_plan` is clear — "active" alone proves nothing for a
  tenant already paying on another plan. A closed popup leaves a "Payment
  pending" banner with a Pay now button (any tenant with a pending plan), and
  the current plan keeps showing as current. Per-bed plans activate on
  selection (rule 19) and never open Checkout. Not built: billing history, the
  suspension lock screen, the Super Admin portal.
- [DECISION 2026-10-18] **Flat plan changes are pending until paid (owner choice
  after review).** Originally `select_plan` swapped `plan` and
  `razorpay_subscription_id` immediately. That let a tenant keep an unpaid
  upgrade by closing Checkout, left the old Razorpay subscription charging, and
  (switching to per-bed) orphaned it so its webhooks matched nothing. The
  alternative considered was rejecting changes for active subscribers; that was
  declined because it would stop paying tenants upgrading in the app. Applies
  to every flat selection, trial tenants included (they previously got the
  chosen plan's limits before paying). Judgement calls, not specified by the
  PRD: the old subscription is cancelled *immediately* when the new one is paid
  (no proration or refund, no cancel-at-cycle-end overlap); a plan paid for after
  the tenant outgrew its cap is applied anyway. Not exercised against real
  Razorpay (stubbed locally): `subscription.cancel(id, {'cancel_at_cycle_end': 0})`
  is called per Razorpay's documented API and mocked in tests. The earlier
  downgrade-vs-bed-create race test no longer applies (the plan doesn't change
  at selection) and was replaced by one asserting selection leaves limits alone.
- [DECISION 2026-10-18] **A durable ledger (`razorpay_subscriptions`) replaces the
  single pending id (owner-requested follow-up to a second review).** The first
  pending-plan design forgot a superseded pending id the moment a newer plan was
  chosen, so a payment for it landing late was dropped (money taken, no plan, no
  record), and a failed cancel was logged once and never retried. It also
  cancelled the old flat subscription *before* the per-bed local writes, which a
  later failure cannot undo. Judgement calls the PRD doesn't cover: a late payment
  on an abandoned choice is **honoured** rather than refunded (the tenant paid for
  that plan; refunding would need a Razorpay refund call I can't verify here); a
  renewal on an already-replaced subscription **is** flagged for manual refund
  (`subscription.payment_needs_refund`), because honouring it would mean two
  live plans. `fetch_razorpay_subscription_status` (Razorpay's subscription fetch,
  `status` field) is used to treat "cancel failed because it is already finished"
  as success; like `cancel`, it is mocked in tests and unverified against real
  Razorpay. Existing live/pending subscriptions are backfilled by migration 0009.
  A third review found the honour-a-late-payment rule raced the cancel worker (it
  could promote a subscription the worker had just cancelled remotely); the CANCELLING
  claim above closes it. Trade-off: a payment that genuinely succeeded before the
  claim but whose webhook is delayed past it is flagged for refund rather than
  honoured, so ops must refund it — chosen over provisioning the tenant on a
  subscription that may already be cancelled. A fourth review found the flagged
  payment could still promote the row on a webhook *replay* after a failed cancel
  restored ABANDONED; payment-id idempotency is now checked before promotion
  (`_reconcile_non_current_event`). A genuinely new payment id on a restored ABANDONED
  row is still honoured — it is a new charge, not the one ops was told to refund.

## Changelog
- 2026-10-18  Public plan catalogue `GET /public/plans/` for the pglive.in marketing
  site (allow-listed serializer, `currency` + `trial_days` envelope, throttled,
  cached 5 min); `PLATFORM_CURRENCY` constant replaces the three `'INR'` literals in
  `razorpay_client.py`. Tests: `test_public_plans` (allow-list, active-only,
  per-bed tiers, config-driven trial days, read-only, no tenant data).
- 2026-10-18  Basic (₹149, 500 beds, trial) + Unlimited (₹249) launch plans,
  `max_beds` cap, 45-day trial, live-plan price lock, single trial plan; see
  rules 21-25 and the Decisions above. Backend tests added in
  `test_bed_limits`, `test_plan_protection`, `test_bed_limit_concurrency`,
  `test_seed_migration` (+ override and signup cases).
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
