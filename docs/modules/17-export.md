# Module: Data Export

> Keep this file in sync with the code AT ALL TIMES.
> If the code and this file disagree, this file is wrong — fix it in the same commit.

**Status:** Done
**Phase:** 3
**PRD reference:** Module 23 (Data Export)
**Depends on:** 04, 08, 09
**Blocks:** none

## Purpose
Downloadable exports (CSV / Excel / PDF) for the four reports the PRD names:
Resident list, Payment history, Outstanding dues, Occupancy report. This is
the last module in the build order — every table it reads from already
exists (Modules 02/04/08/09).

## Data model (as-built)
No new table. Four `APIView`s in `apps.reporting` each build a
`(columns, rows)` table on request from existing models (`Resident`,
`Payment`/`Invoice`, `Bed`) and hand it to one of three renderers.

## API endpoints
```
GET /api/v1/exports/residents/?filetype=csv|xlsx|pdf&property=<uuid>          view_resident_profile
GET /api/v1/exports/payments/?filetype=csv|xlsx|pdf&property=<uuid>            manage_payments
GET /api/v1/exports/outstanding-dues/?filetype=csv|xlsx|pdf&property=<uuid>    manage_invoices
GET /api/v1/exports/occupancy/?filetype=csv|xlsx|pdf&property=<uuid>           view_reports
```
`filetype` defaults to `csv`; an unrecognised value is a 400
(`invalid_filetype`). `property` is optional on all four — omit it to export
everything the caller can see.

## Business rules (each maps to a test)
1. Each export is scoped by `visible_property_ids()` exactly like every
   other list endpoint — Owner/Super Admin see the whole tenant, Manager
   only assigned properties. An explicit `?property=` outside that set
   silently returns an empty table (no 403/404) — same as filtering any
   other list endpoint by an id you can't see.
2. Resident list gates on `view_resident_profile` (includes Receptionist —
   same data the resident list screen already shows them). Payment history
   and Outstanding dues gate on `manage_payments`/`manage_invoices`
   respectively (exclude Receptionist — same as the live endpoints they
   mirror). Occupancy gates on `view_reports` (`_OPS`).
3. Payment history and Outstanding dues reuse the exact same derived logic
   as their live endpoints: `balance_due`/`is_overdue()` are computed from
   `Invoice`, never a stored field (invariant already established in Module
   08/09) — a fully-paid invoice past its due date is correctly excluded
   from Outstanding dues, not shown as overdue.
4. Occupancy counts beds by `status` (`available`/`occupied`/`reserved`/
   `maintenance`) per property, plus an occupancy percentage
   (`occupied / total_beds`, one decimal place, `0.0` for a property with no
   beds yet).
5. CSV/Excel/PDF all render the identical `(columns, rows)` table — no
   report has format-specific columns.

## Permissions
- `view_resident_profile` (Super Admin, Owner, Manager, Receptionist):
  Resident list export.
- `manage_payments` (Super Admin, Owner, Manager): Payment history export.
- `manage_invoices` (Super Admin, Owner, Manager): Outstanding dues export.
- `view_reports` (Super Admin, Owner, Manager): Occupancy export.
- No new permissions — every export reuses the permission already gating
  the live resource it exports.

## Edge cases handled
- `?filetype=` is validated against a fixed whitelist (`csv`, `xlsx`,
  `pdf`) before any row-building happens.
- A resident with no `Allocation` (never checked in) exports with a blank
  "Room / Bed" column rather than an error.
- A property with zero beds shows `0` across every occupancy column and
  `0.0%`, not a division-by-zero.

## Open questions / Decisions
- [DECISION 2026-07-05] **Query parameter is `filetype`, not `format`.**
  DRF's `DefaultContentNegotiation` reads `?format=` itself
  (`URL_FORMAT_OVERRIDE`) to select a *renderer* on every `APIView`, and
  raises `Http404` during content negotiation — before the view's `get()`
  ever runs — when no registered renderer's `format` attribute matches the
  value. Since these endpoints don't register `csv`/`xlsx`/`pdf` renderers
  (they return a plain `HttpResponse`, not a DRF `Response`), `?format=csv`
  collided with DRF's own machinery and 404'd before reaching any of this
  module's code. Renaming the parameter sidesteps the collision entirely
  rather than fighting DRF's content negotiation to reclaim the name.
- [DECISION 2026-07-05] **Renderers return a plain Django `HttpResponse`,
  not a DRF `Response`.** CSV/XLSX/PDF aren't things DRF's renderer/parser
  framework is built around (they're not JSON-serializable representations
  of one resource) — `HttpResponse` with an explicit `Content-Type` and
  `Content-Disposition: attachment` is the standard Django way to serve a
  file download, and `APIView.get()` is free to return one directly.
- [DECISION 2026-07-05] **Out-of-scope `?property=` returns empty, not
  403/404.** Consistent with how every other list endpoint's `?property=`
  filter behaves when combined with RLS/assignment scoping — filtering
  narrows within what you can already see; it was never a lookup that
  asserts the id exists.
- [DECISION 2026-07-05] **No `Content-Length`/streaming for very large
  exports.** All four reports build their full row list in memory before
  rendering. Acceptable at MVP scale (PRD's target is small PG/hostel
  operations, not thousands of residents per tenant); revisit with
  streaming/pagination if a real tenant's export becomes slow.
- [BUG FIXED 2026-07-05] **`WeasyPrint==62.*` crashed on `write_pdf()`**
  (`AttributeError: 'super' object has no attribute 'transform'`) because
  `pydyf>=0.12` removed `Stream.transform()`, which WeasyPrint 62.x's PDF
  backend still calls via `super()`. Import succeeded fine — only actual
  rendering failed — so this wasn't caught until this module tried to
  render a real PDF. Fixed by pinning `pydyf==0.11.*` in
  `requirements/base.txt`. Also added `openpyxl==3.*` for the Excel export
  (nothing in the codebase used either dependency's actual functionality
  before this module).

## Changelog
- 2026-06-xx  Created stub.
- 2026-07-05  Built: `apps.reporting.export` (csv/xlsx/pdf renderers, one
  Django HTML template for the PDF table), `apps.reporting.services` (one
  row-builder per report, all reusing `visible_property_ids` scoping), four
  `APIView`s + urls. Pinned `pydyf==0.11.*` (WeasyPrint 62.x compatibility
  bug — see Decisions) and added `openpyxl==3.*`. 16 new tests (per-format
  content correctness, permission gating per export, Manager property
  scoping, overdue/fully-paid dues filtering, occupancy bed-status
  counting). Full suite (410) green. Spec written to as-built.
