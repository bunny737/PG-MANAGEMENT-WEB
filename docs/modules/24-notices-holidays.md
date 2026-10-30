# Module: Notices & Food Holidays

> Keep this file in sync with the code AT ALL TIMES.
> If the code and this file disagree, this file is wrong — fix it in the same commit.

**Status:** In progress — backend done; frontend (FE-24) not started
**Phase:** 3
**PRD reference:** PRD §9 Resident App "View notices"; the food-holiday credit is an owner request
(2026-10-30), not in PRD v2
**Depends on:** 02, 03, 08, 10, 15
**Blocks:** none

## Purpose
During festivals (Dasara, Sankranti…) PGs give residents a few days when they can stay but no food is
served. Some owners credit the food for those days on the next bill; some don't. Owners also need to post
notices to their residents.

- **Food holidays**, per property. A holiday can optionally adjust bills, crediting each with-food resident
  `rate_per_day` × the holiday days they stayed, as its own negative invoice line.
- **Notices** (`Announcement` in code): a per-property notice board. A food holiday can auto-post one.

Both go through the shared REST API. Residents have no login yet, so delivery is the notice board only (owner
decision). The future resident app reads the same endpoints.

## Data model (as-built)
All three tables are RLS-enforced (`apps.notices`). Money fields are `decimal(12,2)`. Narrower bounds are
enforced by validation and DB CHECKs.
```
Table: announcements
  id, tenant_id, property FK (CASCADE; immutable after create)
  title varchar(200), body text, category general|holiday|maintenance|rules|event
  is_pinned bool, expires_on date null
  is_auto_text bool         -- title/body are still the text generated from the linked holiday
  generated_from jsonb null -- holiday snapshot the text is known to match; NEVER serialized (holds the rate)
  created_by FK users (SET_NULL), created_at, updated_at

Table: food_holidays
  id, tenant_id, property FK (PROTECT; immutable after create)
  name varchar(100), start_date, end_date (inclusive)
  adjust_in_bill bool, rate_per_day decimal(12,2) null
  announcement OneToOne -> announcements null (SET_NULL)
  created_by, created_at, updated_at
  CHECK end_date >= start_date; CHECK 0 <= rate_per_day <= 999,999.99; CHECK adjust_in_bill => rate set
  service: span <= 366 days; no overlap with another holiday of the same property

Table: food_holiday_credits     -- what one resident is owed for one holiday
  id, tenant_id, holiday FK (PROTECT), resident FK (PROTECT)
  days, rate, amount            -- CHECK amount = rate × days
  status pending | invoiced | settled | waived
  line_item OneToOne -> invoice_line_items null (PROTECT)
  vacate FK null (PROTECT), absconded_record FK null (PROTECT)
  clawback_days, clawback_amount -- CHECK clawback_amount = rate × clawback_days <= amount
  UNIQUE (holiday, resident)
  CHECK status/references: pending|waived -> no line, no settlement ref, no clawback
                           invoiced -> line; a settlement ref only together with a clawback
                           settled  -> no line, exactly one of vacate / absconded_record
```
Changes to other modules' tables:
- `property_settings.food_charge_per_day` (null, 0–999,999.99): the default rate the holiday form prefills.
- `invoice_line_items.line_type` gains `food_holiday`.
- `vacates`: `food_holiday_credit`, `food_holiday_clawback_calculated`, `_recovered`, `_unrecovered`, all ≥ 0
  with CHECK `calculated = recovered + unrecovered`.
- `absconded_records`: `food_holiday_credit`, `food_holiday_clawback`, both ≥ 0.

## API endpoints
```
GET|POST         /api/v1/notices/                         view_notices / manage_notices  ?property=&category=&active=
GET|PATCH|DELETE /api/v1/notices/{id}/
POST             /api/v1/notices/{id}/mark-current/       manage_notices — clears notice_outdated
GET|POST         /api/v1/food-holidays/                   view_notices / manage_notices (+ manage_invoices, below) ?property=
GET|PATCH|DELETE /api/v1/food-holidays/{id}/
GET              /api/v1/food-holidays/{id}/credits/      view_notices + view_finance — stored rows + "estimated" rows
POST             /api/v1/food-holidays/{id}/credits/{cid}/restore/   manage_notices + manage_invoices
```
`GET /vacates/{id}/settlement-preview/` also accepts `?actual_vacate_date=` and returns the food-holiday
figures. Vacate and absconded-record payloads include the new fields.

## Business rules (each maps to a test in `apps/notices/tests/`)
1. **Entitlement** = holiday days ∩ [joining date, departure date], only for `with_food` admissions and only
   while `adjust_in_bill` is on (`credits.entitled_days`, pure).
2. **Timing.** A credit is created and put on a bill only once the holiday has ended
   (`end_date < local_today()`). A move-out or abscond is the one exception: it settles the days actually
   stayed, unfinished holiday included.
3. **Allocation** (`credits.allocate_pending`, the only pending → invoiced path):
   - Candidates are the resident's **drafts** with `period_start > holiday.end_date`, earliest first.
     Issued invoices are never touched.
   - Pending credits go in order of `(end_date, start_date, id)`. Each lands on the first candidate where
     the total stays **> 0**.
   - A credit that fits nowhere stops the queue (strict FIFO).
   - Credits already attached never move.
   - Allocation reruns after: invoice generation (manual, bulk, auto), draft line add/edit/delete, draft
     delete, holiday create/edit, restore, and the daily task.
4. **Daily task.** `notices.allocate_food_holiday_credits` runs at 05:30 IST (migration 0002; fallback
   `manage.py allocate_food_holiday_credits --date`).
   - One effective date for the whole run.
   - Each property runs in its own transaction under its tenant's RLS context.
   - It processes residents missing a credit for an ended holiday, plus residents with any pending credit
     (so a credit that didn't fit is retried).
5. **Food-holiday lines are system-owned.**
   - Adding one, retyping a line to `food_holiday`, or PATCHing one is rejected (`line_locked`).
   - Deleting it **waives** the credit for that resident. The waived row stays as a tombstone: it survives
     date, rate and adjust-off/on edits.
   - `restore` brings a waived credit back. Rejected with `resident_not_current` for a Vacated or Absconded
     resident, and with `adjustment_off` while the adjustment is off.
6. **Rebalance.** After another line change leaves a draft ≤ 0, its credits are detached in descending
   `(end_date, start_date, id)` until total > 0, then re-offered. Owner lines alone at ≤ 0 are left as set.
7. **Holiday edits** recompute each affected resident (locked in id order):
   - draft credits are detached and pending rows rebuilt;
   - adjust-off removes pending and invoiced credits.

   Once any credit is on an issued invoice or settled, dates, rate and `adjust_in_bill` are frozen
   (`holiday_locked`, 409). The name and notice stay editable, and delete is refused.
8. **Move-out** (`finalize_vacate`):
   - Non-issued, non-waived credits are settled with `through = actual_vacate_date`; draft lines are removed
     first. The sum goes to `food_holiday_credit`.
   - Credits on issued bills covering days after the move-out are clawed back
     (`calculated = Σ rate × extra days`).
   - `recovered = min(calculated, max(0, deposit − deduction + advance_refundable + credit))`. Only
     `recovered` reduces the refund. `unrecovered` is informational, since dues are never netted on a
     normal move-out.
   - The preview runs the same read-only plan (`credits.plan_exit`) and writes nothing.
9. **Abscond:**
   - pool = deposit + unapplied advance + food-holiday credit;
   - dues = outstanding + full clawback;
   - `applied = min(pool, dues)`; the surplus is forfeited.
10. **Bounds.** Every persisted aggregate (credit, clawback figures, abscond pool and dues) is checked
    against 9,999,999,999.99 before saving (`settlement_amount_too_large`).
11. **Notices.**
    - Holiday create auto-posts a `holiday` notice (toggle `post_notice`, default on). It says whether
      charges are adjusted, never the rate.
    - Any holiday edit regenerates title and body while `is_auto_text`.
    - An owner text edit clears `is_auto_text` and re-confirms `generated_from`.
    - `notice_outdated` (derived) = customised and `generated_from` ≠ current holiday snapshot. Saving the
      text or `mark-current` clears it.
    - Deleting a holiday deletes its notice only if the text is still auto-generated.
12. **Permissions.**
    - `view_notices` (Owner, Manager, Receptionist), `manage_notices` (Owner, Manager): new `notices` module
      in `core/modules.py`, Receptionist default `view`; accounts 0012 backfills saved overrides.
    - `manage_invoices` is also required to create an adjusting holiday, or to edit or delete one where the
      current **or** submitted `adjust_in_bill` is true.
    - Without `view_finance`, `rate_per_day`, `credit_total` and `credit_count` are removed from responses.
13. **Isolation.** All three tables are RLS-enforced (`TenantIsolationTests`).

## Locking
Every path that writes holidays or credits takes the property's `PropertySettings` row lock first, which
serializes them per property. Global order:
`PropertySettings → FoodHoliday (NO KEY UPDATE) → Resident → Vacate → Invoice → FoodHolidayCredit → Admission`.

The Settings lock was added in front of:
- `generate_invoice` (manual and bulk; automatic billing already held it);
- `finalize_vacate` and `mark_absconded`;
- invoice delete and line add/edit/delete.

These orderings are covered by threaded tests against real PostgreSQL (`test_concurrency.py`).

## Decisions
- [DECISION 2026-10-30] (owner) Credit = ₹ per day × days stayed. There is a property default; each holiday
  can override it.
- [DECISION 2026-10-30] (owner) Whole days only (no per-meal holidays).
- [DECISION 2026-10-30] (owner) Unused credit at move-out is added to the refund.
- [DECISION 2026-10-30] (owner) Unused credit at abscond joins the pool netted against dues; the surplus is
  forfeited like the deposit.
- [DECISION 2026-10-30] (owner) A backdated departure after an issued credit is clawed back in the settlement
  (capped at the refund on a move-out; added to the dues on an abscond).
- [DECISION 2026-10-30] (owner) Delivery is the notice board only for now. No email or WhatsApp; resident
  push waits for resident login.
- [DECISION 2026-10-30] `Announcement` is the model name, to avoid confusion with notice period (Module 10)
  and `AutoBillingNotice` (Module 08).
- [DECISION 2026-10-30] Credits are created lazily: on bill generation, holiday save, the daily task, or exit.
  Residents admitted after a holiday was saved are therefore still covered. Read-only views use estimates.
- [DECISION 2026-10-30] A credit is never attached before its holiday ends. Otherwise a September-generated
  November draft could refund an October holiday the resident never reached.
- [DECISION 2026-10-30] A bill's total never goes to ≤ 0 because of credits. A zero-total issued invoice
  would stay `issued` and later show as overdue (`Invoice.is_overdue`).
- [DECISION 2026-10-30] Food-holiday lines are not editable. Waive (delete) and restore are the per-resident
  controls, and the line amount always equals `days × rate`.
- [DECISION 2026-10-30] The credit FKs are `PROTECT`, so a path bypassing `apps.notices.credits` (admin, a
  cascade) fails loudly. The admin for credits is read-only.
- [DECISION 2026-10-30] Credits stop when a stay ends. A holiday entered after a resident's settlement creates
  nothing for them; the owner adjusts by hand.
- [DECISION 2026-10-30] Line labels are stored English text ("Food holiday — Dasara (4 days × ₹100.00)"),
  built like the existing generated labels (`_accommodation_label`, discount label).
- [OPEN] Telugu translations for the new gettext strings are not in `locale/te` yet.
- [OPEN] Frontend (FE-24): Notices page (Notices / Food holidays tabs), settings field, invoice line display,
  checkout and absconded rows.

## Changelog
- 2026-10-30  Backend built: `apps.notices` (models, RLS, credits service, sweep and beat task, command,
  admin, API), plus billing / residents / properties hooks and fields. 84 tests (credits, settlement, API,
  races). The billing, residents, core, properties, reporting, onboarding and module-access suites are green.
  ERD regenerated.
