# Module: Expenses

> Keep this file in sync with the code AT ALL TIMES.
> If the code and this file disagree, this file is wrong — fix it in the same commit.

**Status:** Done
**Phase:** 3
**PRD reference:** none — owner request 2026-10-16 (UX roadmap Phase 4, "D5")
**Depends on:** 01, 02, 15
**Blocks:** 21 (analytics `expenses_paid` / `net_cash_flow`), 17 (expense + cash-flow exports)

## Purpose
Record what the PG spends (rent/lease, electricity, salaries, groceries, …) per
property, so the owner sees the outflow side next to rent collected: a monthly
list with totals by category, and — through Module 21 — net cash flow.

## Data model (as-built)

```
Table: expense_categories                      (RLS enforced, app: apps.expenses)
  id            uuid PK            stable id clients store
  tenant_id     uuid (RLS)
  code          varchar(30)        system categories only ('' for custom)
  name          varchar(60)        custom categories only ('' for system)
  is_system     bool
  is_archived   bool               hidden from pickers, still labels old rows
  order         smallint
  UNIQUE (tenant_id, code) WHERE is_system
  UNIQUE (tenant_id, lower(name)) WHERE NOT is_system
  CHECK  system => code != ''  /  custom => code = '' AND name != ''

Table: expenses                                (RLS enforced)
  id, tenant_id
  property        FK properties (PROTECT)      required
  category        FK expense_categories (PROTECT)
  amount          decimal(12,2) > 0            (CHECK)
  date            date                         not in the future
  payment_mode    upi | cash | bank_transfer | card | cheque | other
  note            text
  attachment      file (S3 / local), random name under expenses/<tenant>/<expense>/
  attachment_content_type   sniffed from magic bytes
  idempotency_key varchar(100) null  UNIQUE (tenant_id, key) WHERE NOT NULL
  created_by / updated_by / deleted_by   FK users (SET_NULL)
  deleted_at      timestamptz null             soft delete
  INDEX (property, date)
```
System categories (code → translated label, `apps/expenses/models.py`):
rent_lease, electricity, water, internet, gas, groceries, salaries,
maintenance, cleaning, laundry, furniture, taxes, marketing, other.

## API endpoints
```
GET|POST      /api/v1/expenses/                       list / create            view_expenses / manage_expenses
GET|PATCH|DEL /api/v1/expenses/{id}/                  detail / edit / soft-delete
GET           /api/v1/expenses/summary/               {month, property, total, count, by_category[]}
GET|PUT|DEL   /api/v1/expenses/{id}/attachment/       signed URL / replace (multipart) / remove
GET|POST      /api/v1/expense-categories/             list (seeds system ones) / add custom
PATCH|DEL     /api/v1/expense-categories/{id}/        rename/archive custom / delete unused custom
GET           /api/v1/exports/expenses/               CSV/XLSX/PDF (Module 17)
```
List filters: `?property=&month=YYYY-MM&category=&payment_mode=&search=&from=&to=`.
`POST /expenses/` accepts JSON or multipart (optional `attachment`) and an
`Idempotency-Key` header (replay → 200 + `Idempotent-Replayed: true`; same
key, different property/amount/date → 409 `IDEMPOTENCY_KEY_REUSED`).
`PUT /expenses/{id}/` (full replace) → 405; PUT is only for the attachment.

## Business rules (each maps to a test — `apps/expenses/tests/test_expenses.py`)
1. `property` is required and must be one of the caller's properties
   (`property_not_assigned`); lists/summary only cover assigned properties;
   `summary?property=` for an unassigned property is 404.
2. `amount > 0` (`invalid_amount`, DB CHECK too); `date` not in the future
   (`future_date`); backdating is allowed.
3. DELETE is a soft delete (`deleted_at`, `deleted_by`): excluded from every
   list, summary, analytics total and export.
4. Every create/update/delete/attachment change is audit-logged
   (`expense.created|updated|deleted|attachment_replaced|attachment_removed`,
   before/after snapshots).
5. Attachments: JPEG/PNG/WebP/PDF detected from magic bytes
   (`attachment_type_not_allowed`), ≤ `EXPENSE_ATTACHMENT_MAX_BYTES`
   (default 5 MB, `attachment_too_large`). Never exposed as a stored URL —
   `GET …/attachment/` returns `{url, content_type, expires_in}` with a signed
   URL valid `EXPENSE_ATTACHMENT_URL_TTL_SECONDS` (default 300) on S3.
6. Categories: system ones are seeded per tenant on first list (idempotent,
   race-safe) and cannot be renamed/archived/deleted (`system_category`);
   custom names are unique case-insensitively (`duplicate_category`); a custom
   category in use can't be deleted (`category_in_use` 409 — archive it); an
   archived category can't be picked for a new/changed expense
   (`category_archived`).
7. Summary reconciles with the list: same live rows, same filters.
8. Tenant isolation: both tables RLS-enforced (proven by
   `ExpenseRowLevelSecurityTests`).

## Permissions
New codes `view_expenses` / `manage_expenses` (both `_OPS`: Super Admin,
Owner, Manager). New module-access entry `expenses` with levels
off / view (`view_expenses`) / full (+`manage_expenses`); role defaults
Manager → full, Receptionist → off. Exposed through `/auth/me/` permissions
and the staff module-access endpoints automatically (registry-driven).

## Edge cases handled
- Concurrent retries with the same Idempotency-Key: the partial unique index
  decides; the loser returns the winner's row.
- Editing an expense into a different month moves it between month lists
  (clients refresh both months — refresh contract).
- Soft-deleted expenses still reference their category, so a category used
  only by deleted expenses still can't be hard-deleted (archive instead).

## Open questions / Decisions
- [DECISION 2026-10-16] **Owner approved the module and its defaults**:
  Manager full, Receptionist off; staff whose module access was already
  customized get the Manager default via data migration
  `accounts.0007_module_access_expenses_default` instead of resolving to
  `off` (the registry's fail-closed default for new modules).
- [DECISION 2026-10-16] **Categories are tenant rows seeded lazily**, not a
  global catalog + tenant table (Module 18's split). One table gives every
  category — system or custom — a stable UUID the client can store, and the
  label of a system category is still translated at render time (`code` →
  gettext), never stored.
- [DECISION 2026-10-16] **Future dates are rejected.** An expense is money
  already spent; a future date is almost always a typo. Scheduled/recurring
  expenses are a client preset feature, not a server concept.
- [DECISION 2026-10-16] **Attachment on PATCH is refused**
  (`use_attachment_endpoint`) so replacing the file is always the explicit
  `PUT …/attachment/` that audits it.
- [OPEN] Recurring expense presets live in the app only for now.

## Changelog
- 2026-10-16  Built: `apps.expenses` (ExpenseCategory, Expense, RLS), CRUD +
  summary + attachment + categories endpoints, permission codes and module
  access entry, data migration for customized staff, export (Module 17),
  analytics inputs (Module 21). Tests in `apps/expenses/tests/`.
