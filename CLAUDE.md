# CLAUDE.md — Agent Rules

Read this file at the start of every session before writing any code.

## What we are building
Multi-tenant SaaS for PG/hostel management in India. Owners manage properties,
residents, billing, and operations through a single system.

## Locked tech stack — do not deviate
- Backend: Python 3.12, Django 5.x, Django REST Framework
- DB: PostgreSQL 16 with Row-Level Security (RLS)
- Queue: Celery + Redis
- Storage: AWS S3
- Payments: Razorpay — platform subscription billing ONLY, never resident rent
- Web Frontend: Next.js 15 (App Router) + TypeScript + Tailwind CSS, installable PWA
  Confirmed by owner 2026-07-02. All frontend work follows docs/frontend-plan.md
  (route map, invariants F1–F8, FE build order, PWA strategy).
- Mobile: Native Android — Kotlin + Jetpack Compose (Retrofit + OkHttp) — later
  phase; the PWA covers the mobile resident experience until then.

## 10 Non-negotiable invariants

1. TENANT ISOLATION: Every business table has tenant_id. Every query is
   tenant-scoped. RLS enforced at DB level, not just app code. Cross-tenant
   query = critical bug. Always add a test proving isolation.

2. contracted_rent IS THE BILLING BASELINE — never rack_rate.
   Contracted rent is snapshotted at admission. Never recompute from room.

3. TEMPORARY ALLOCATION: Bill at contracted_rent regardless of which room
   the resident physically occupies. Temporary room rack rate is irrelevant.

4. DISCOUNTS: Applied on contracted_rent, not rack_rate. Two residents in
   the same room can have different discounts. Show as separate invoice line.

5. MONEY = Decimal always. Never float.
   Use DecimalField(max_digits=12, decimal_places=2) everywhere.

6. INVOICE = list of line items. Never hardcode fixed fields. The engine
   must iterate a list so future add-ons (diet food, gym) drop in with zero
   changes. Keep reserved addons JSON field (empty [] in MVP).

7. NO HARDCODED UI STRINGS. Every user-facing string goes through i18n
   (gettext server-side). English only in MVP but plumbing is mandatory now.

8. STATUS LIFECYCLES are exact. Only Active + Notice Period count toward
   plan resident limits. Inquiry/Reserved/Vacated/Absconded/Blacklisted do not.

9. AUDIT LOG every critical mutation: before/after values, user, timestamp, IP.

10. PLAN LIMITS ARE CONFIG, NOT CONSTANTS. Never hardcode 60 (trial days),
    5 (grace days), property caps, or resident caps. All live in Super Admin config.

## Build order — strict dependency sequence
01 auth-tenancy → 02 property-hierarchy → 03 property-settings → 04 residents
→ 05 admissions → 06 allocations → 07 discounts → 08 billing → 09 payments
→ 10 deposits-exit → 11 complaints → 12 visitors → 13 subscription
→ 14 notifications → 15 audit-logs → 16 activity-timeline → 17 export

## Per-task workflow
1. Read this file + the relevant docs/modules/<nn>.md spec
2. Check all dependencies are ✅ in docs/modules/README.md
3. Implement: model → migration → serializer → view/permission → test
4. Write tests for every business rule + one tenant-isolation test
5. Update the module spec to match what was actually built (same commit)
6. Update docs/modules/README.md status
7. Record every judgement call in the module spec under "Decisions"

## When to stop and ask (do not guess)
- PRD is silent or ambiguous on a money rule or status transition
- Task requires a new dependency or cross-module schema change
- Frontend work that deviates from docs/frontend-plan.md (stack, auth model,
  offline/PWA write behaviour, or the FE build order)
