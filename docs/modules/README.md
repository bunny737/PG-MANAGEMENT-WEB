# Module Index & Status Board

Build strictly top to bottom. Do not start a module until all dependencies are ✅.

## Status
⬜ Not Started · 🟨 In Progress · ✅ Done

| # | Module | Spec file | Phase | Depends on | Status |
|---|--------|-----------|-------|------------|--------|
| 01 | Tenancy, Auth & Roles | 01-auth-tenancy.md | 1 | none | ✅ |
| 02 | Property → Building → Floor → Room → Bed | 02-property-hierarchy.md | 1 | 01 | ✅ |
| 03 | Property Settings | 03-property-settings.md | 1 | 02 | ✅ |
| 04 | Residents | 04-residents.md | 1 | 02 | ✅ |
| 05 | Admissions | 05-admissions.md | 1 | 04 | ✅ |
| 06 | Allocations & Transfers | 06-allocations.md | 1 | 05 | ✅ |
| 07 | Discounts | 07-discounts.md | 2 | 06 | ✅ |
| 08 | Invoices / Billing | 08-billing.md | 2 | 06, 07 | ✅ |
| 09 | Payments | 09-payments.md | 2 | 08 | ✅ |
| 10 | Deposits / Advance / Vacating / Absconded | 10-deposits-exit.md | 2 | 08 | ✅ |
| 11 | Complaints | 11-complaints.md | 3 | 04 | ✅ |
| 12 | Visitors | 12-visitors.md | 3 | 04 | ✅ |
| 13 | Subscription + Razorpay + Plan Limits | 13-subscription.md | 3 | 01, 02 | ✅ |
| 14 | Notifications | 14-notifications.md | 3 | 08, 09 | ✅ |
| 15 | Audit Logs | 15-audit-logs.md | 3 | 01 | ✅ |
| 16 | Activity Timeline | 16-activity-timeline.md | 3 | 04 | ✅ |
| 17 | Data Export | 17-export.md | 3 | 04, 08, 09 | ✅ |
| 18 | PG Features | 18-pg-features.md | 3 | 02 | ✅ |
| 19 | App Client (version policy, devices, force-update) | 19-app-client.md | 3 | 01, 14, 15 | ✅ |
| 20 | Expenses (owner request 2026-10-16, not in PRD v2) | 20-expenses.md | 3 | 01, 02, 15 | ✅ |
| 21 | Analytics, property layout, resident finance (UX roadmap D0–D9) | 21-analytics.md | 3 | 02, 04, 08, 09, 10, 20 | ✅ |
| 22 | Account Deletion (Google Play requirement, 2026-10-23, not in PRD v2) | 22-account-deletion.md | 3 | 01, 13, 14, 15, 19 | 🟨 |
| 23 | Getting Started: setup checklist, empty-state hints, tutorial videos (owner request 2026-10-28, not in PRD v2) | 23-getting-started.md | 3 | 01, 02, 03, 04, 05, 20 | ✅ |
| 24 | Notices & Food Holidays: notice board, food-holiday bill credits (owner request 2026-10-30, not in PRD v2) | 24-notices-holidays.md | 3 | 02, 03, 08, 10, 15 | 🟨 (backend and web UI done; move-out / abscond rows wait on FE-10) |
| 25 | PG Discovery: public nearby-PG search, contact + inquiries behind a verified login (owner request 2026-10-31, not in PRD v2) | 25-pg-discovery.md | 3 | 01, 02, 03, 05, 13, 14, 18, 22, 26a | ⬜ |
| 26 | Resident Identity & App Access: resident accounts, invites, join-code link requests, post-exit access (owner request 2026-10-31, not in PRD v2) | 26-resident-identity.md | 3 | 26a: 01, 04, 10, 14, 22 · 26b: 08, 09, 11, 12, 13, 19, 24 | 🟨 (26a ✅, 26b ⬜) |

## Cross-cutting (enforced in every module — not built once)
- Tenant isolation + RLS
- i18n string externalisation (no hardcoded strings)
- Decimal money (no floats)
- Audit logging on critical mutations
- Configurable limits (no hardcoded caps or durations)

## Frontend
Next.js + PWA frontend confirmed 2026-07-02. Plan, route map, invariants, and the
FE status board live in [../frontend-plan.md](../frontend-plan.md). Each FE task
starts only after its backend module above is ✅ (FE-00 foundation may start
immediately against OpenAPI mocks).
