# Module: Notices & Food Holidays

> Keep this file in sync with the code AT ALL TIMES.
> If the code and this file disagree, this file is wrong — fix it in the same commit.

**Status:** In progress — backend and web UI done; the move-out / abscond food-holiday rows wait on FE-10 (the web app has no move-out or abscond screen yet)
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
GET              /api/v1/food-holidays/{id}/credits/      view_notices + view_finance — {credits: stored + "estimated" rows, totals}
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
- [DECISION 2026-10-30] Django admin is **view-only** for holidays, notices and credits. A plain admin save
  would skip the edit lock, overlap check, credit reconciliation and audit trail; `PROTECT` only guards
  deletes.
- [DECISION 2026-10-30] Account deletion (Module 22): all three models are `(PURGE, RETAIN)`. A tenant purge
  deletes credits first (they PROTECT invoice lines, residents and settlements), then holidays (they PROTECT
  the property), then notices.
- [DECISION 2026-10-30] Every credit transition is audited as the staff member who triggered it, with the
  request IP: creation, allocation, recompute, detach/waive/restore, settle, clawback and delete. Only the
  scheduled sweep writes actor-less entries.
- [DECISION 2026-10-30] A holiday edit locks and re-reads its notice before regenerating it. A concurrent
  owner text edit therefore either commits first (and is seen as customised) or waits, and is never
  overwritten. The notice is locked last; notice edits take only that lock.
- [DECISION 2026-10-31] `GET .../credits/` returns `{credits: [...], totals: {...}}`, not a bare list. The totals
  are computed on the server (Decimal): `credited` = pending + invoiced + settled rows (the same definition as the
  holiday's `credit_total`), with `credited_count`; `estimated` / `estimated_count` (residents who qualify
  now but have no stored credit); `waived_count` (a count only, a waived credit is not owed); and `clawback`.
  Estimates, waived rows and clawbacks are never part of `credited`. The web client shows these figures and
  never adds money up itself (frontend invariant F1).
- [DECISION 2026-10-31] Web UI (FE-24), at `/notices` (tabs Notices / Food holidays, `?tab=`) and
  `/notices/holidays/[id]`:
  - `view_notices` opens the page; `manage_notices` shows add / edit / delete and both buttons of the
    "notice may be out of date" banner (without it, the warning text alone).
  - The holiday detail is its own route (credits table, notice, edit, delete). The list rows link to it; edit and
    delete live there.
  - A holiday that adjusts bills shows Edit and Delete only with `manage_invoices` (the backend enforces it
    against the locked row either way). A locked holiday (`is_locked`) disables its dates, adjustment and
    rate in the form and its Delete; the API gives no reason, so the explanation is client copy, and a 409
    `holiday_locked` from a change that raced an issued bill is still shown and the holiday refetched.
  - The default rate (`PropertySettings.food_charge_per_day`) pre-fills a NEW holiday only, and only for a
    user who can read property settings (`manage_property_settings`). Editing never reads the settings and
    never sends a field it didn't change, so a saved rate isn't replaced by the current default and a rate
    withheld from a user without `view_finance` is never sent back. The default is derived from the settings
    of the property chosen now, never copied into state, so a late response for another property cannot win
    and a rate the user typed is never overwritten.
  - A notice deep link (`/notices?tab=notices&notice=<id>`, used by the holiday list's "notice may be out of
    date" warning) fetches that one notice and shows it above the list whatever the Active / Expired / category
    filters are. An expired notice can be edited while keeping its expiry (the "not before today" check is a
    client guard for a newly chosen date only; the backend has no such rule).
  - On an invoice, a `food_holiday` line is system-owned: no edit, and Delete reads "Waive".
  - Cache: notices queries are invalidated by the shared refresh helpers (`afterInvoiceChange`,
    `afterInvoiceIssued`, `afterVacate`), because generating, editing, issuing or deleting an invoice and
    settling a stay all change credits and the holiday lock, not only the holiday screens.
- [OPEN] Move-out and abscond screens (FE-10) must show the food-holiday credit and clawback rows. The API
  already returns them (`food_holiday_credit`, `food_holiday_clawback_*`); `afterVacate` already refreshes
  notices.
- [DONE 2026-10-31] Telugu translations for the gettext strings are in `locale/te` (28 entries). The
  generated auto-notice text is therefore produced in the viewer's language.

## Changelog
- 2026-10-31  Web UI built (FE-24): Notices page with Notices and Food holidays tabs, holiday detail with the
  credits table and Restore, the "food charge per day" setting, and waive-only `food_holiday` invoice lines.
  Backend: `GET .../credits/` now also returns server-computed totals (see Decisions). Telugu `.po`
  entries added.
- 2026-10-30  Backend built: `apps.notices` (models, RLS, credits service, sweep and beat task, command,
  admin, API), plus billing / residents / properties hooks and fields. 84 tests (credits, settlement, API,
  races). The billing, residents, core, properties, reporting, onboarding and module-access suites are green.
  ERD regenerated.
- 2026-10-30  Review fixes:
  - (1) registered in account deletion (`DISPOSITION` / `PURGE_ORDER`); the tenant-purge end-to-end test now
    seeds a holiday, a notice and an invoiced credit;
  - (2) admin is view-only;
  - (3) holiday edits and deletes lock the notice before regenerating or deleting it (race test added);
  - (4) actor and request flow through every credit transition, recomputed amounts are audited, and the
    sweep stays actor-less (tests added).
- 2026-10-30  Review fixes:
  - `generate_invoice` now works from the locked resident re-read and refuses a resident who left or lost
    their bed meanwhile (`ResidentNotBillable`, 400; bulk generation skips them), so a generate racing a
    move-out can't create credits after the settlement (race test);
  - holiday create/update re-validate the merged dates, span and rate under the lock (`invalid_dates`,
    `holiday_too_long`, `rate_required`), so concurrent PATCHes can't combine into reversed dates (a 500)
    or an over-long span (race and unit tests).
- 2026-10-30  Review fix: the `manage_invoices` requirement for editing or deleting a holiday is checked in
  `update_holiday` / `delete_holiday` against the **locked** row (current or submitted `adjust_in_bill`),
  not in the view against the copy read before the lock. An adjustment switched on in between can no longer
  let a user without invoice rights change or delete it (deterministic stale-read test plus a threaded
  race).
