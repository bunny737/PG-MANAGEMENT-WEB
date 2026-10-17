# UX roadmap — backend contract (Phases 2–6)

Backend for the "PG Mate UX improvement roadmap". Module specs hold the full
rules: [20 Expenses](modules/20-expenses.md),
[21 Analytics & layout](modules/21-analytics.md), plus additions in
[01](modules/01-auth-tenancy.md), [02](modules/02-property-hierarchy.md),
[05](modules/05-admissions.md), [08](modules/08-billing.md),
[09](modules/09-payments.md), [17](modules/17-export.md).

All paths are under `/api/v1/`. Money is always a Decimal **string**
(`"7000.00"`); rates (`occupancy_rate`, `collection_rate`) are JSON numbers
(percent, 1 dp) or `null`. Errors carry an upper-case `code`.

## Answers the plan asked the backend for

| Question | Answer |
|---|---|
| Phase 1 release gate: does `POST /payments/` reject overpay, incl. two concurrent payments? | **Yes.** Balance re-checked under an invoice row lock (`OVERPAYMENT`); a concurrency test proves only one of two racing payments lands. `Idempotency-Key` is now supported too. |
| Do lists return only the first page? | **No pagination anywhere** — every list returns the full array. `extractResults` vs `fetchAllPages` makes no difference today. |
| Rent refunds / credits | **Not modelled in v1** (owner decision). `refunds_paid` is always `"0.00"`; deleting a payment is the reversal. No credit balance exists anywhere. |
| Property timezone | Single product timezone (`Asia/Kolkata`); responses echo `timezones: ["Asia/Kolkata"]`. The "mixed timezones" note never triggers today. |
| Side effects for the refresh contract | Admission, transfer, vacate (notice/cancel/finalize) and absconded **create no invoices, payments or refunds**. **Issuing** a resident's first invoice auto-records the admission advance as a payment → refresh payments, cash movements, invoice, resident finance, layout, analytics after `POST /invoices/{id}/issue/`. Absconded snapshots `remaining_dues` (read-only). |

## Authorization model (D1, D2, D6)
1. Property scope: `?property=` must be assigned to the caller → else **404**.
   Omitted = all assigned properties.
2. Entry permission per endpoint → else **403**.
3. Field groups the caller can't see are `null` and listed in top-level
   `redacted: [...]`. A `null` not in `redacted` = no data.

| Endpoint | Entry (any of) | Groups (permission) |
|---|---|---|
| `GET properties/{id}/layout/` | view_property_features, manage_rooms_beds, manage_admissions, manage_allocations | `resident` (view_resident_profile), `payment` + `finance` (view_finance) |
| `GET residents/{id}/` | view_resident_profile | `finance` (view_finance) |
| `GET analytics/summary/`, `analytics/trend/` | view_reports, view_dashboard | `finance` (view_finance), `expenses` (view_expenses), `cash_flow` (both); `occupancy` always |

Note: module levels are cumulative, so anyone with `manage_allocations`
(Tenants→Full) also has `view_resident_profile`.

## D3 — list filters
| Endpoint | Params |
|---|---|
| `invoices/` | `property, resident, billing_mode, period=YYYY-MM, search, status` — status = comma list of `draft,issued,partially_paid,paid` **or** `outstanding` / `overdue` alone |
| `invoices/outstanding/` | same filters; identical to `?status=outstanding` |
| `payments/` | `property, resident, invoice, payment_mode, month, from, to, search` (name/phone/receipt no./reference) |
| `cash-movements/` | `property, month` or `from`+`to` (default: this month) |
| `residents/` | `property, status` (comma list), `search` (name/phone) |
| `rooms/` | `property, building, floor, category, status` |
| `beds/` | `property, room, status, availability` (multi) |
| `expenses/` | `property, month, category, payment_mode, search, from, to` |

New row fields: invoices and payments carry `resident_name, property,
property_name, room_number, bed_number`; invoices `capped_allocated`;
payments `resident, receipt_number, invoice_period_start/end,
recorded_by_name`; rooms `property, building`.

`cash-movements/` → `{from, to, gross_receipts, refunds_paid, total, count,
results:[{type:"payment", id, date, amount, receipt_number, payment_mode,
invoice, resident, resident_name, property, property_name}]}`.

## Payment integrity + receipts (D3, D4)
- `POST payments/` with header `Idempotency-Key: <≤100 chars>`: first call
  201; a retry with the same key and body → **200** + header
  `Idempotent-Replayed: true` and the original payment (even if the invoice is
  now fully paid). Same key, different invoice/amount → 409
  `IDEMPOTENCY_KEY_REUSED`. Generate one key per *user intent* (per dialog
  submit), not per HTTP attempt.
- `receipt_number` `RCT-000001`… per tenant, never reused.
- `GET payments/{id}/receipt/` JSON (adds `receipt_number`, room/bed,
  `invoice_paid`, `recorded_by_name`, `created_at`); `?filetype=pdf` → A5 PDF
  (`Content-Disposition: receipt-RCT-000001.pdf`) for the share sheet.

## D6 — resident finance block (`GET residents/{id}/`, detail only)
```json
"finance": {
  "current_period": {
    "period": "2026-10",
    "invoices": [{"id","period_start","period_end","total","paid","balance","due_date","status","is_overdue"}],
    "total": "7000.00", "paid": "2500.00", "balance": "4500.00",
    "status": "no_invoice | paid | partially_paid | unpaid | overdue",
    "has_draft": false
  },
  "outstanding_total": "10500.00", "overdue_total": "6000.00",
  "prior_outstanding": "6000.00", "last_payment_date": "2026-10-16"
},
"redacted": []
```
Card mapping: no invoice → `status: no_invoice` (+ `prior_outstanding` for
"₹X outstanding from earlier"; `has_draft` for "draft not issued"); several
invoices → `invoices[]` summed; arrears line → `prior_outstanding` with
drill-down `invoices/?resident=&status=outstanding`.

## D2 — property layout (`GET properties/{id}/layout/?period=YYYY-MM`)
```json
{
  "property": {"id","name"}, "period": "2026-10", "as_of": "2026-10-16", "due_soon_days": 7,
  "counts": {"total","occupied","reserved","maintenance","available","occupancy_rate"},
  "finance": {"outstanding_total","overdue_total","open_invoice_count",
              "residents_with_balance_count","occupied_beds_with_balance_count"},
  "buildings": [{"id","name","order","counts","floors": [{"id","name","order","counts",
    "rooms": [{"id","room_number","sharing_type","category","status",
               "rack_rate_with_food","rack_rate_without_food","counts",
      "beds": [{"id","bed_number","availability","reserved_for","reserved_until",
                "rack_rate_with_food","rack_rate_without_food",
                "resident": {"id","name","phone","status","on_notice","notice_date",
                             "expected_vacate_date","is_temporary"},
                "payment": {"status":"paid|upcoming|due|overdue|no_invoice",
                            "period_balance","overdue_balance"}}]}]}]}],
  "redacted": []
}
```
Dues banner: `finance.outstanding_total` + `finance.residents_with_balance_count`
→ drill to `invoices/?property=&status=outstanding`. `occupancy_rate: null`
→ "No beds yet" (`counts.total == 0`) or "All beds under maintenance".

## D9 — bed transitions (`PATCH beds/{id}/`)
Allowed: available ↔ maintenance, available ↔ reserved, reserved ↔ maintenance
(reserved may carry `reserved_for` (Inquiry/Reserved resident of the same
property) and `reserved_until`; leaving reserved clears them). Anything into or
out of `occupied` → **409 `BED_TRANSITION_NOT_ALLOWED`**. Admission accepts a
reserved bed held for that resident or for nobody. Delete: occupied/reserved →
400 `BED_NOT_VACANT`; any resident history → 409 `BED_HAS_HISTORY`.
`PATCH rooms/{id}/` can't drop `sharing_type` below the bed count
(`ROOM_CAPACITY_BELOW_BEDS`).

Every bed object — on `GET/PATCH beds/{id}/` and inside `layout/` — carries
`allowed_transitions: string[]`: the availability values a plain PATCH may
move *this* bed to right now (`[]` for `occupied`). A client never hardcodes
the table above; it renders only what `allowed_transitions` lists, and PATCH
is the final authority regardless.

## Web client note (2026-10-17)
This contract backs a Next.js web client (`frontend/`) in addition to the
Flutter app the roadmap was written for — same API, no per-client branching
(frontend-plan.md §3.1a). Two additions landed for it, both backward
compatible (existing fields unchanged):
- `allowed_transitions` on beds (D9, above) — the frontend invariant F8
  ("the frontend never invents transitions") needs a served source instead
  of a copy of the table above.
- `@extend_schema` response annotations on every endpoint in this doc that
  returns a hand-built dict rather than a `ModelSerializer` (analytics
  summary/trend, the property layout, cash-movements, the payment receipt,
  the expense summary and attachment GET, and the resident finance block) —
  so `/api/schema/` → `openapi-typescript` gives the web client a real type
  instead of `unknown`. See each module's 2026-10-17 Decisions entry (hub:
  Module 21) and `apps/reporting/tests/test_schema.py`.
- The discount list (`GET /discounts/`) gained the same `resident_name,
  property, property_name, room_number, bed_number` columns as invoices and
  payments, plus a `?property=` filter — see Module 07.

**The web client itself** (`/billing`, `/expenses`, `/reports`, the
`/properties/{id}` bed grid, the residents/dashboard rework) is `feature/
ux-roadmap-web`, branched from this one — see `docs/frontend-plan.md` §11's
2026-10-17 rows for what shipped, what was deliberately deferred (invoice
PDF, waive-with-note, refunds/credits, a reserve-for-resident dialog), and
the type-generation reversal (schema generated and committed, but existing
hand-written types in `lib/api.ts` weren't migrated to it).

## D5 — expenses
See [20-expenses.md](modules/20-expenses.md). Permissions `view_expenses` /
`manage_expenses` appear in `/auth/me/` `permissions` and as module `expenses`
(off/view/full) in the staff module-access payload. Categories: fetch
`expense-categories/` first (seeds the built-ins; use `id`, show `label`).
Attachments: multipart field `attachment` on create, `PUT|DELETE
expenses/{id}/attachment/`, `GET` → `{url, content_type, expires_in}`.
Summary: `expenses/summary/?property=&month=` → `{month, property, total,
count, by_category:[{category, name, code, total, count}]}`.

## D0/D1 — analytics
Glossary and response shapes: [21-analytics.md](modules/21-analytics.md).
YTD start = `tenants/current/` `fiscal_year_start_month` (default 4).
Trend: `analytics/trend/?end=YYYY-MM&months=6` (1–24).

## D7 — exports
`exports/payments/?month=`, `exports/outstanding-dues/?period=`,
`exports/expenses/?property=&month=`, `exports/pnl/?property=&month=`
(cash-flow statement; needs view_finance + view_expenses). Format param is
`filetype=csv|xlsx|pdf` (not `format`).

## Not built (by decision or still open)
- Rent refunds, resident credit ledger (owner decision 2026-10-16).
- `as_of` historical balances (v1 = current balances only).
- D8 automated reminders — open questions in the plan still stand (resident
  accounts/devices don't exist). The manual WhatsApp click-to-chat needs no
  backend.
