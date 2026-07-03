# Module: Discounts

> Keep this file in sync with the code AT ALL TIMES.
> If the code and this file disagree, this file is wrong — fix it in the same commit.

**Status:** Done
**Phase:** 2
**PRD reference:** Module 8 (Resident Discount Management)
**Depends on:** 06
**Blocks:** 08

## Purpose
Owner/Manager grant a per-resident discount (fixed ₹ or %) with a reason,
approver, and validity window. Module 08 (Billing) applies it on top of
`contracted_rent` as its own invoice line (invariant 4). This module owns
the discount records + validation only; the actual invoice math and
discount reports are Module 08 / reporting.

## Data model (as-built)

```
Table: discounts                                (RLS enforced, app: apps.billing)
  id                uuid PK
  tenant_id         uuid              (RLS)
  resident          FK -> residents.Resident (PROTECT)   ← discount scope
  discount_type     fixed | percentage
  discount_value    decimal(12,2)     (₹ amount, or % value)
  reason            loyalty | referral | corporate | negotiated | seasonal | other
  note              text, blank
  valid_from        date
  valid_until       date, null        (null = indefinite)
  approved_by       FK -> users, null (SET_NULL)   ← stamped from request user
  created_at / updated_at
```

## API endpoints
```
GET|POST   /api/v1/discounts/          list (filter ?resident= ?reason= ?discount_type=) / create   manage_discounts
GET|PATCH  /api/v1/discounts/{id}/     detail / update                                              manage_discounts
```
No DELETE — end a discount by PATCHing `valid_until` (consistent with the
platform's no-hard-delete stance for financial records).

## Business rules (each maps to a test)
1. Discount attaches to a **resident** (== allocation level, since
   Allocation is 1:1 with Resident) — two residents in the same room can
   hold different discounts (invariant 4).
2. `approved_by` is stamped server-side from the request user (never client
   input) — the Owner/Manager who created it.
3. Validation: `discount_value` must be > 0; a `percentage` discount must be
   ≤ 100; `valid_until` (if set) cannot precede `valid_from`.
4. **At most one active discount per resident at a time** — creating/updating
   a discount whose window overlaps another of the same resident's discounts
   is rejected (`overlapping_discount`). Windows are inclusive, so sharing a
   single day counts as overlap. Different residents may of course have
   overlapping windows.
5. `manage_discounts` (Super Admin, Owner, Manager) gates every action;
   Receptionist and Resident get 403. Manager/Receptionist are scoped to
   their assigned properties via the resident's property (reuses
   `apps.properties.services` — an unassigned property → `property_not_assigned`).
6. Create and update write audit logs (`discount.created` / `discount.updated`
   with before/after).
7. `discounts` is RLS-enforced; isolation proven the same way as the other
   modules' tables.
8. `Discount.computed_amount(contracted_rent)` returns the discount figure
   (percentage → % of contracted rent, rounded half-up to 2dp; fixed → the
   flat value) and `is_active_on(date)` answers the validity window — both
   pure helpers Module 08 will call. Unit-tested without the DB.

## Permissions
- `manage_discounts` (Super Admin, Owner, Manager): all endpoints, scoped to
  assigned properties for Manager.
- Receptionist and Resident: no access.

## Edge cases handled
- Boundary overlap: `[07-01, 07-31]` and `[07-31, 08-31]` share `07-31` and
  are rejected; `[07-01, 07-31]` and `[08-01, …]` are allowed.
- Indefinite discounts (`valid_until = null`) are treated as open-ended in
  the overlap check (they conflict with any later window for that resident).
- Percentage rounding uses `ROUND_HALF_UP` to 2 decimals (money = Decimal,
  invariant 5).

## Open questions / Decisions
- [DECISION 2026-07-03] **At most one active discount per resident at a
  time** (no overlapping validity windows). Every PRD invoice example shows
  a single discount line, and invariant 4 describes "a separate invoice
  line" (singular, per resident) — so discounts are not stacked. Enforcing
  non-overlapping windows keeps Module 08's per-period discount selection
  deterministic. Not raised with the product owner as it's the clear PRD
  reading; revisit in Module 08 if genuine stacking is ever required.
- [DECISION 2026-07-03] **`Discount` lives in `apps.billing`** (its first
  model), not `apps.residents`. It's a money modifier consumed by billing,
  and this keeps the dependency direction clean (billing → residents).
  Modules 08/09/10 will join it there.
- [DECISION 2026-07-03] Discount scope FK is to **Resident**, not
  Allocation. They're 1:1, but the resident is the stable anchor across
  transfers (a transfer doesn't reset the resident's discount), and it
  reads naturally as "this resident's discount."
- [DECISION 2026-07-03] A fixed discount is **not** capped at
  `contracted_rent` here. Module 08 owns final invoice math and will clamp
  payable to ≥ 0; validating a fixed discount against the rent now would be
  fragile (the rent can change, and a discount can exist before check-in).
- [DECISION 2026-07-03] No hard delete (create + PATCH only); a discount is
  ended by setting `valid_until`. Matches the platform-wide financial-record
  handling and keeps the record intact for Module 08 invoice references.
- [OPEN] PRD "Discount Reports" (total discount given this month, # residents
  on discount, breakdown by reason) are **not** built here. "Total given
  this month" needs invoices (Module 08); the rest are simple aggregations
  best placed with dashboards / Module 17 (Data Export). Deferred.
- [OPEN] A discount can currently be created for a resident who isn't yet
  admitted (no `contracted_rent`). That's intentional (the PRD reason
  "Negotiated at admission" implies it can be recorded around admission),
  and harmless — Module 08 only applies it once there's a contracted rent to
  apply it to.

## Changelog
- 2026-06-xx  Created stub.
- 2026-07-03  Built: `Discount` model (RLS, in apps.billing) with
  fixed/percentage types, reason + validity window + approver, non-overlap
  enforcement, property-scoped CRUD (no delete), audit logging, and
  `computed_amount`/`is_active_on` helpers for Module 08. 24 tests. Spec
  written to as-built.
