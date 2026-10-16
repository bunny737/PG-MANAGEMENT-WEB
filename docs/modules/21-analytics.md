# Module: Analytics & Property Layout (UX roadmap backend)

> Keep this file in sync with the code AT ALL TIMES.
> If the code and this file disagree, this file is wrong — fix it in the same commit.

**Status:** Done
**Phase:** 3
**PRD reference:** none — owner request 2026-10-16 (UX roadmap Phases 2–6: D0, D1, D2, D6)
**Depends on:** 02, 04, 08, 09, 10, 20
**Blocks:** Flutter/web Analytics, Property detail bed grid, Resident current-month card

## Purpose
Owner-facing "at a glance" numbers that are defined once on the server and
drill down to lists using the same definition: a metric glossary (D0), a
month summary + trend (D1), the whole bed grid in one call (D2), and a
finance block on resident detail (D6).

## Data model (as-built)
No tables of its own. Supporting changes elsewhere:
- `tenants.fiscal_year_start_month` (smallint 1–12, default 4 = Indian FY) —
  YTD start; editable on `PATCH /tenants/current/` (Module 01).
- `platform_config.payment_due_soon_days` (default 7) — the bed-grid "due"
  window (invariant 10: config, not a constant).

## API endpoints
```
GET /api/v1/analytics/summary/?property=&month=YYYY-MM          entry: view_reports OR view_dashboard
GET /api/v1/analytics/trend/?property=&end=YYYY-MM&months=6     entry: view_reports OR view_dashboard (months 1–24)
GET /api/v1/properties/{id}/layout/?period=YYYY-MM              entry: view_property_features OR manage_rooms_beds
                                                                       OR manage_admissions OR manage_allocations
GET /api/v1/residents/{id}/                                     + `finance` block (view_finance) and `redacted`
```

## Metric glossary (D0) — `apps/reporting/analytics.py`, `apps/billing/selectors.py`
All amounts are INR Decimal strings. Month = calendar month in the property
timezone (`apps/core/periods.py`; every property is `Asia/Kolkata` today and
responses echo `timezones`).

| Field | Definition | Drill-down that sums to it |
|---|---|---|
| gross_receipts | payments with `payment_date` in the month | `/payments/?month=` |
| refunds_paid | rent refunds in the month — **always 0 in v1** | — |
| cash_collected | gross_receipts − refunds_paid | `/cash-movements/?month=` (`total`) |
| period_invoiced | current net total of issued (non-draft) invoices whose `period_start` is in the month ("to date") | `/invoices/?period=` `total` |
| period_collected | Σ min(paid, max(net total, 0)) over those invoices | `/invoices/?period=` `capped_allocated` |
| collection_rate | period_collected ÷ period_invoiced, % with 1 dp; `null` when nothing invoiced; ≤ 100 by construction | — |
| outstanding_total | balance of issued/partially-paid invoices with balance > 0, any period, **as of now** | `/invoices/?status=outstanding` |
| period_outstanding | the same, limited to the month's invoices | `/invoices/?period=&status=outstanding` |
| overdue_total | outstanding with `due_date` < today | `/invoices/?status=overdue` |
| open_invoice_count / residents_with_balance_count / occupied_beds_with_balance_count | counts, never compared with each other | — |
| deposits_held | Σ (security deposit + unapplied advance) of Active/Notice residents — a liability, never income | — |
| expenses_paid | live expenses dated in the month | `/expenses/?month=` |
| net_cash_flow | cash_collected − expenses_paid ("Net cash flow", not profit) | — |
| ytd_* | flow metrics from the fiscal-year start to min(month end, today) | — |

Summary response: `{month, property, timezones, balances_as_of, ytd{start,end},
occupancy{total,occupied,reserved,maintenance,available,occupancy_rate},
finance{…}|null, expenses{expenses_paid, ytd_expenses_paid}|null,
cash_flow{net_cash_flow, ytd_net_cash_flow}|null, redacted[]}`.
Trend: `{end, months, property, timezones, series[{month, finance, expenses, cash_flow}], redacted[]}`.

## Authorization model (D1/D2/D6)
1. **Property scope** — `?property=` must be one of the caller's properties
   (else 404, `properties.services.scoped_property_ids`); without it the
   figures cover every assigned property.
2. **Entry permission** per endpoint (table above); missing → 403.
3. **Field groups** are redacted by their own permission: `null` + listed in
   top-level `redacted` (never a 403). Derived groups need every constituent
   permission (`cash_flow` = view_finance + view_expenses). A `null` not in
   `redacted` means "no data". Helper: `apps/core/redaction.py`.

| Endpoint | Group | Needs |
|---|---|---|
| analytics | finance / expenses / cash_flow | view_finance / view_expenses / both; occupancy: entry only |
| layout | resident (and `reserved_for`) / payment / finance | view_resident_profile / view_finance / view_finance; room & bed rack rates always |
| resident detail | finance | view_finance |

## Layout (D2) — `apps/properties/layout.py`
Buildings → floors → rooms → beds, `counts` at every level. Bed:
`{id, bed_number, availability, reserved_for{id,name}|null, reserved_until,
rack_rate_with_food, rack_rate_without_food, resident|null, payment|null}`.
- `resident` = CURRENT occupant only (Active/Notice allocation):
  `{id, name, phone, status, on_notice, notice_date, expected_vacate_date, is_temporary}`.
- `payment.status` (first match): `overdue` (any overdue balance) →
  `no_invoice` (no issued invoice starting in the period) → `paid` →
  `due` (balance due within `payment_due_soon_days`, incl. due today) →
  `upcoming`. Plus `period_balance`, `overdue_balance`.
- A previous occupant's dues never colour a vacant bed; they appear in the
  property `finance` block (`outstanding_total, overdue_total,
  open_invoice_count, residents_with_balance_count,
  occupied_beds_with_balance_count`) — the dues banner.
- `occupancy_rate` = occupied ÷ (total − maintenance) as %, `null` when the
  denominator is 0.

## Resident finance block (D6) — `apps/residents/finance.py`
`finance = {current_period{period, invoices[{id, period_start, period_end,
total, paid, balance, due_date, status, is_overdue}], total, paid, balance,
status: no_invoice|paid|partially_paid|unpaid|overdue, has_draft},
outstanding_total, overdue_total, prior_outstanding, last_payment_date}` —
detail only (not on the list). Drafts never count.

## Business rules (each maps to a test)
1. Every summary figure equals the sum of its drill-down list
   (`reporting/tests/test_analytics.py::test_figures_reconcile_with_their_drill_downs`).
2. collection_rate is null with nothing invoiced and ≤ 100 after a
   post-payment credit.
3. Soft-deleted expenses never count.
4. YTD follows `tenant.fiscal_year_start_month`.
5. Permission matrix: dashboard+finance without reports → finance shown;
   finance without dashboard/reports → 403; reports without finance →
   finance & cash_flow redacted; finance without expenses → cash_flow redacted.
6. Layout: counts, null occupancy when all beds are in maintenance, the five
   payment states, vacant beds never coloured by past occupants, redaction for
   Receptionist / finance-off / tenants-off staff, 403 without an entry code,
   404 for unassigned or other-tenant property (`properties/tests/test_layout.py`).
7. Resident finance block states and redaction
   (`residents/tests/test_resident_finance.py`).

## Open questions / Decisions
- [DECISION 2026-10-16] **No rent-refund model in v1** (owner decision).
  `refunds_paid` is always `0.00`; cash movements are payments only. Deleting
  a payment is the "reversal" (it simply no longer exists). Deposit/advance
  refunds at vacate are excluded by definition.
- [DECISION 2026-10-16] **No credit ledger.** Overpayment is rejected
  (Module 09) and line items are editable only on drafts, so today a net
  total can't drop below what was paid; the `min()` cap in period_collected
  only guards a future credit feature. Nothing reports a credit balance.
- [DECISION 2026-10-16] **Single timezone.** Properties have no timezone field;
  the product timezone (`settings.TIME_ZONE`) is every property's zone and is
  echoed as `timezones`. Adding per-property zones means changing
  `core.periods.property_timezones` and the month bucketing together.
- [DECISION 2026-10-16] **Rates are JSON numbers** (`occupancy_rate`,
  `collection_rate`: percent, 1 dp) — they are ratios, not money (invariant 5
  covers money, which stays Decimal strings).
- [DECISION 2026-10-16] **Drafts are excluded** from every figure (period
  invoiced, outstanding, the bed payment state, the resident card) — a draft is
  not yet an obligation (Module 08). The resident card exposes `has_draft`
  so the UI can say "Draft not issued".
- [DECISION 2026-10-16] **`deposits_held` includes the unapplied advance**,
  since both are refunded at vacate (`Vacate.refund_amount`).
- [DECISION 2026-10-16] **Plan matrix case "manage_allocations only →
  resident redacted" is unreachable**: module levels are cumulative, so
  Tenants→Full (which carries manage_allocations) always includes
  view_resident_profile. Tested instead: entry via Tenants→Full with
  Properties and Finance off → payment/finance redacted, resident shown.
- [DECISION 2026-10-16] Balances are always as of now; no `as_of` parameter
  in v1 (would have to land on summaries, invoices, payments, expenses and
  exports together).

## Changelog
- 2026-10-16  Built: analytics summary/trend, property layout, resident finance
  block, shared selectors/periods/redaction helpers, tenant fiscal-year
  setting, `payment_due_soon_days` config. Tests listed above.
