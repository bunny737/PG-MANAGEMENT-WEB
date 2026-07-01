# Module: Invoices / Billing

> Keep this file in sync with the code AT ALL TIMES.
> If the code and this file disagree, this file is wrong — fix it in the same commit.

**Status:** Not Started
**Phase:** 2
**PRD reference:** Module 9 (Rent & Billing)
**Depends on:** 06, 07
**Blocks:** 09, 10, 14, 17

## Purpose
What does this module let a user do?

## Data model (as-built)
Document tables as actually implemented, not as originally planned.

```
Table: <name>
  id
  tenant_id       FK → tenants   (RLS enforced)
  ...
  created_at
  updated_at
```

## API endpoints
```
METHOD  /api/v1/<path>/    purpose    permission
```

## Business rules
Each rule maps to a test.
1.
2.

## Permissions
Which roles can do what.

## Edge cases handled
-

## Open questions / Decisions
- [DECISION 2026-06-xx] what was decided and why
- [OPEN] unresolved — needs input

## Changelog
- 2026-06-xx  Created stub.
