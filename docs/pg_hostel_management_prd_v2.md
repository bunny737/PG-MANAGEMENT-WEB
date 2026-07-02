# PG/Hostel Management SaaS Platform
## Product Requirements Document (PRD) — Version 2.9

> Last Updated: June 2026
> Status: Pre-Build Planning

---

# 1. Project Overview

## Product Name
PG/Hostel Management SaaS Platform

## Vision
A cloud-based multi-tenant SaaS platform that enables PG owners, hostel operators, and co-living businesses to manage their properties, residents, finances, operations, and staff through a single centralized system — replacing spreadsheets, notebooks, and WhatsApp groups with a clean digital workflow.

## Problem Statement
Most PGs and hostels manage operations using spreadsheets, notebooks, WhatsApp groups, and manual processes. This creates challenges such as:

- Inaccurate occupancy tracking
- Delayed rent collection
- Poor complaint management
- Lack of financial visibility
- Manual paperwork and data loss risks
- Difficulty managing multiple properties
- No audit trail for payments and decisions

---

# 2. Business Goals

## Primary Goals
- Increase operational efficiency for PG owners
- Reduce manual work and paperwork
- Improve rent collection rates and visibility
- Provide real-time occupancy insights
- Enable multi-property management from a single dashboard
- Create predictable recurring SaaS revenue

## Secondary Goals
- Mobile-first resident experience
- Automated notifications
- Business analytics and reporting
- White-label solutions for large customers

---

# 3. Target Customers

## Customer Segments

### Segment 1 — Small PG Owners (Primary MVP Target)
- 1–2 properties
- 20–100 residents
- Currently managing via spreadsheets/WhatsApp

### Segment 2 — Medium Hostel Operators
- 3–10 properties
- 100–1,000 residents

### Segment 3 — Large Hostel Chains
- Multiple cities
- Thousands of residents

### Segment 4 — Co-Living Operators
- Shared living spaces
- Working professionals

---

# 4. Subscription & Pricing Model

## Free Trial
- **60 days free** on signup — no credit card required
- Full access to all plan features during trial
- Reminder notifications at Day 45 and Day 55

## Pricing Tiers

Pricing is based on two dimensions — **number of properties** and **number of active residents** per property. Both limits are **configurable by Super Admin** and will be finalised based on market feedback at the time of marketing launch.

| Plan | Properties | Active Residents (per property) | Price/Month |
|------|-----------|--------------------------------|-------------|
| Starter | 1 | TBD | ₹199 |
| Basic | Up to 3 | TBD | ₹499 |
| Growth | Up to 10 | TBD | ₹999 |
| Enterprise | Unlimited | Unlimited | ₹2,499 |

> **Limits are TBD** — actual resident caps per plan will be decided during marketing. The system stores these as configurable values in the Super Admin panel, not hardcoded in the application. Changing a limit requires no code deployment — only a config update.

## What Counts as an Active Resident

For the purpose of plan limit enforcement, **active residents** are those with status:
- Active
- Notice Period *(still occupying a bed)*

**Not counted:**
- Inquiry
- Reserved *(bed held but not yet checked in)*
- Vacated
- Absconded
- Blacklisted

## Pricing Rules
- All plans include the same core feature set — no feature gating between tiers
- Limits are enforced on both properties and active residents
- Resident count is checked per property, not across all properties combined

## Plan Limit Enforcement
- **Hard block** when either limit (property or resident) is reached
- Clear in-app upgrade prompt shown at the point of block with plan comparison
- No auto-upgrade — owner explicitly selects the new plan
- Super Admin can manually override limits for a specific tenant if needed (e.g. grace period, enterprise negotiation)

## Configurable Limits in Super Admin Panel
Super Admin can update the following per plan without any code change:
- Maximum properties allowed
- Maximum active residents per property
- Trial duration (currently 60 days)
- Grace period on payment failure (currently 5 days)

This means limits can be adjusted as part of marketing campaigns, promotional offers, or plan restructuring at any time.

## Subscription Billing
- Razorpay handles all subscription billing (recurring)
- Razorpay is used **only for platform subscription payments** — not for resident rent collection
- Payment failure grace period: 5 days before account suspension
- Suspended accounts: login blocked, data preserved
- Deleted accounts: data retained for 30 days before permanent deletion

## Subscription Lifecycle
```
Signup
→ 60-Day Free Trial (Starter plan features)
→ Day 45: "Your trial ends in 15 days" reminder
→ Day 55: "Your trial ends in 5 days" reminder
→ Day 60: Select Plan → Razorpay payment → Active subscription
→ Monthly auto-renewal
→ Plan upgrade/downgrade available anytime (effective next billing cycle)
```

---

# 5. SaaS Architecture

## Multi-Tenant Model
Each customer account is a **Tenant**. Every tenant can manage multiple properties under one account.

```
Tenant A (PG Owner)
  ├── Boys Hostel, Madhapur
  ├── Girls Hostel, Kondapur
  └── Staff Accommodation, Gachibowli

Tenant B (Hostel Operator)
  ├── Student Hostel, Ameerpet
  └── Executive PG, Banjara Hills
```

## Tenant Isolation Strategy
- **Row-level isolation** using `tenant_id` on every business table
- PostgreSQL Row-Level Security (RLS) enforced at the database level
- Every API query automatically scoped to the authenticated tenant
- No cross-tenant data leakage possible at query level

### Tables Requiring tenant_id
- tenants, properties, floors, rooms, beds
- residents, admissions, allocations
- invoices, payments, deposits
- complaints, visitors
- staff, notifications
- audit_logs, activity_timeline

---

# 6. User Roles & Permissions

## Role Overview

The platform uses a simplified 5-role model designed to match how small and medium PGs actually operate — where one person often handles multiple functions, and the owner frequently manages everything themselves.

| Role | Level | Who They Are |
|------|-------|-------------|
| Super Admin | Platform | Platform operator — manages all tenants and subscriptions |
| Owner | Tenant | PG owner — full control over all their properties |
| Manager | Tenant | Operations staff — handles all day-to-day work across assigned properties |
| Receptionist | Tenant | Front desk only — visitors and basic resident lookup |
| Resident | Tenant | Self-service — views own data and raises complaints |

> **Removed roles:** Accountant, Warden, and the old narrowly-scoped Manager are consolidated into the new **Manager** role. A Manager can now handle admissions, billing, complaints, allocations, and visitor management — everything operations-related.

---

## Platform Level

### Super Admin
- Manage all tenant accounts
- Manage and configure subscription plans
- Monitor platform health and usage metrics
- Handle support escalations
- View platform-wide analytics
- Suspend / reactivate tenant accounts

---

## Tenant Level

### Owner
- Full access to **all properties** under the tenant account
- Create and manage Manager and Receptionist accounts
- Assign Managers to one or multiple properties
- Property settings configuration (billing rules, penalties)
- Financial management — invoices, payments, deposits
- Reports and analytics
- Plan upgrade / downgrade
- Can perform all Manager and Receptionist actions directly from their own account

> **Self-operated mode:** When an owner manages the PG themselves without any staff, they use the Owner account to perform all operations. No Manager account is required.

### Manager
- Assigned to **one or multiple properties** by the Owner
- Sees only the properties they are assigned to
- Full operations access on assigned properties:
  - Resident management (create, edit, vacate)
  - Admission workflow (inquiry → check-in)
  - Room and bed allocation (including temporary allocation)
  - Transfer management
  - Invoice generation and management
  - Payment recording (manual entry) including partial payments
  - Discount management
  - Security deposit and advance management
  - Vacating workflow and deduction entry
  - Complaint management
  - Visitor management
  - Attendance marking *(V2)*
  - View occupancy and financial dashboards

> **Multi-property assignment:** One Manager can be assigned to multiple properties. Their dashboard shows a property switcher to work across their assigned properties. They cannot access properties not assigned to them.

### Receptionist
- Assigned to **one or multiple properties** by the Owner
- Lightweight front-desk role with limited access:
  - Log visitor entry and exit
  - Visitor approval (with Owner/Manager confirmation if required)
  - View visitor history
  - Search and view resident profile (read-only)
  - Cannot access billing, invoices, allocations, or reports

### Resident
- View own profile and document status
- View invoices and payment history
- Download payment receipts
- Raise and track complaints
- Submit visitor requests
- View notices

---

## Property Assignment Rules

- Owner has access to all properties automatically — no assignment needed
- Manager and Receptionist must be **explicitly assigned** to properties by the Owner
- Assignment can be to a single property or multiple properties
- Owner can reassign or remove a Manager/Receptionist from a property at any time
- Removing assignment does not delete the user account — they simply lose access to that property

### Assignment Example
```
Owner: Ramesh (access to all 3 properties)

Manager: Suresh
  ├── Boys Hostel, Madhapur      ✔ assigned
  ├── Girls Hostel, Kondapur     ✔ assigned
  └── Staff Quarters, Gachibowli ✗ not assigned

Receptionist: Lakshmi
  ├── Boys Hostel, Madhapur      ✔ assigned
  ├── Girls Hostel, Kondapur     ✗ not assigned
  └── Staff Quarters, Gachibowli ✗ not assigned
```

---

## Permission Matrix

| Permission | Super Admin | Owner | Manager | Receptionist | Resident |
|-----------|:-----------:|:-----:|:-------:|:------------:|:--------:|
| manage_tenants | ✔ | ✗ | ✗ | ✗ | ✗ |
| manage_subscription | ✔ | ✔ | ✗ | ✗ | ✗ |
| manage_properties | ✔ | ✔ | ✗ | ✗ | ✗ |
| manage_property_settings | ✔ | ✔ | ✗ | ✗ | ✗ |
| manage_staff_accounts | ✔ | ✔ | ✗ | ✗ | ✗ |
| assign_staff_to_properties | ✔ | ✔ | ✗ | ✗ | ✗ |
| manage_rooms_beds | ✔ | ✔ | ✔ | ✗ | ✗ |
| manage_residents | ✔ | ✔ | ✔ | ✗ | ✗ |
| manage_admissions | ✔ | ✔ | ✔ | ✗ | ✗ |
| manage_allocations | ✔ | ✔ | ✔ | ✗ | ✗ |
| manage_invoices | ✔ | ✔ | ✔ | ✗ | ✗ |
| manage_payments | ✔ | ✔ | ✔ | ✗ | ✗ |
| manage_deposits | ✔ | ✔ | ✔ | ✗ | ✗ |
| manage_discounts | ✔ | ✔ | ✔ | ✗ | ✗ |
| manage_complaints | ✔ | ✔ | ✔ | ✗ | ✗ |
| manage_visitors | ✔ | ✔ | ✔ | ✔ | ✗ |
| view_resident_profile | ✔ | ✔ | ✔ | ✔ | ✗ |
| view_reports | ✔ | ✔ | ✔ | ✗ | ✗ |
| view_own_profile | — | — | — | — | ✔ |
| view_own_invoices | — | — | — | — | ✔ |
| raise_complaint | — | — | — | — | ✔ |
| request_visitor | — | — | — | — | ✔ |

---

# 7. Core Modules

---

## Module 1: Authentication & Authorization

### Login Methods
- Email & Password
- Mobile OTP
- Google Login *(V2)*

### Security Features
- JWT Authentication with Refresh Tokens
- Password Reset via email
- Email Verification on signup
- MFA *(V2)*
- Rate limiting on auth endpoints

### Session Management
- Access token expiry: 15 minutes
- Refresh token expiry: 7 days
- Force logout on plan suspension

---

## Module 2: Property Management

### Property Hierarchy
```
Property
  └── Floors
        └── Rooms
              └── Beds
```

### Property Information
- Property Name
- Property Type (Boys Hostel / Girls Hostel / PG / Co-Living Space)
- Address, City, State, Country
- Contact Number and Email
- Status (Active / Inactive)
- Total floors, rooms, beds (auto-calculated)

---

## Module 2B: Property Settings

Each property has a configurable settings panel accessible by Owner and Manager. These settings control how billing, transfers, and penalties behave for that specific property. Different properties under the same tenant can have different settings.

---

### Setting 1 — Room Transfer Rent Change Timing

**When a resident transfers to a different room mid-month, when does the new rent apply?**

| Option | Behaviour |
|--------|-----------|
| **Immediately** | New rent applies from the transfer date. Current month invoice is split: old rent for days in old room, new rent for days in new room. Management manually adjusts the invoice. |
| **Next Billing Cycle** | Resident continues to be billed at old contracted rent for the remainder of the current month. New rent applies from the 1st of the following month. |

- Default: **Next Billing Cycle** (simpler, fewer invoice adjustments)
- Setting is per-property, configurable at any time
- Change in setting applies to transfers made after the change, not retroactively
- Transfer record always stores: `previous_rent`, `new_rent`, `transfer_date`, `rent_effective_date`

**How it appears in the transfer workflow:**

```
Transferring Resident: Ravi Kumar
From: Room 201B (₹4,000/month)  →  To: Room 305A (₹5,000/month)
Transfer Date: 15 Jun 2026

Rent Change Setting: Next Billing Cycle
New Rent Effective: 01 Jul 2026

[ Confirm Transfer ]
```

---

### Setting 2 — Shared Invoices

**Can multiple residents share a single invoice?**

- **No** — Each resident always gets their own individual invoice
- This is a fixed rule, not configurable
- Rationale: residents have individual contracted rents, discounts, food preferences, and partial payment histories — shared invoices would create reconciliation complexity

---

### Setting 3 — Late Payment Penalty

**Is a penalty charged when a resident pays after the due date?**

| Option | Behaviour |
|--------|-----------|
| **No Penalty** | No extra charge for late payment. Owner follows up manually. |
| **Fixed Amount** | A fixed ₹ penalty added to the invoice after the due date |
| **Percentage** | A % of the outstanding amount added as penalty after due date |

**Penalty Configuration Fields (when enabled):**

```
penalty_type              → Fixed / Percentage
penalty_value             → ₹ amount or % value
penalty_grace_days        → number of days after due date before penalty applies
                            (e.g., 5 days grace — penalty kicks in on Day 6)
penalty_applies_to        → Full invoice amount / Outstanding balance only
penalty_compounding       → One-time / Monthly (if still unpaid next month)
```

**Example — Fixed Penalty:**
```
Invoice Due Date          01 Jun 2026
Grace Period              5 days
Penalty Kicks In          06 Jun 2026
Penalty Amount            ₹200 (fixed)

Invoice Breakdown (paid on 10 Jun):
  Rent                    ₹5,000
  Late Payment Penalty    ₹200
  ──────────────────────────────
  Total Payable           ₹5,200
```

**Example — Percentage Penalty:**
```
Invoice Due Date          01 Jun 2026
Grace Period              5 days
Penalty Rate              2% of outstanding
Resident paid ₹2,000 on 05 Jun (within grace — no penalty)
Remaining ₹3,000 unpaid until 10 Jun (past grace)

Penalty = 2% of ₹3,000 = ₹60
```

**Penalty Behaviour Rules:**
- Penalty is added as a separate line item on the invoice — never silently baked into rent
- Management can waive a penalty on a per-invoice basis with a mandatory note
- Penalty waiver is recorded in audit log (who waived, when, reason)
- If `penalty_compounding = Monthly`, an additional penalty cycle is added if invoice remains unpaid into the next month

---

### Property Settings Summary Table

| Setting | Options | Default | Configurable By |
|---------|---------|---------|----------------|
| Room Transfer Rent Timing | Immediately / Next Billing Cycle | Next Billing Cycle | Owner, Manager |
| Shared Invoices | No (fixed) | No | Not configurable |
| Late Payment Penalty | No Penalty / Fixed / Percentage | No Penalty | Owner, Manager |
| Penalty Grace Days | 0–30 days | 5 days | Owner, Manager |
| Penalty Compounding | One-time / Monthly | One-time | Owner, Manager |

---

### Where Settings Live in the UI

```
Property Dashboard
  └── Settings (gear icon)
        ├── General (name, type, address)
        ├── Billing Settings
        │     ├── Room Transfer Rent Timing
        │     ├── Late Payment Penalty
        │     └── Penalty Grace Period
        └── Operational Settings
              └── (future settings go here)
```

---

## Module 3: Room Management

### Room Information
- Room Number
- Floor
- Sharing Type (1-sharing / 2-sharing / 3-sharing / 4-sharing)
- Total bed capacity
- Current occupancy (auto-calculated)
- Room Category (AC / Non-AC)
- Rack Rate — With Food (monthly rent when food is included)
- Rack Rate — Without Food (monthly rent when food is not included)
- Status (Available / Occupied / Reserved / Maintenance)

### Room Category

Rooms are categorised as either **AC** or **Non-AC**. Each room has two rack rates set by management — one for residents who take food, one for those who don't.

```
Room 201 — 4-sharing | AC     | With Food ₹7,000 | Without Food ₹5,500
Room 202 — 4-sharing | Non-AC | With Food ₹5,500 | Without Food ₹4,000
Room 301 — 2-sharing | AC     | With Food ₹10,000 | Without Food ₹8,000
```

### Rack Rate Logic

```
Sharing Type  +  Category  +  Food Pref   =  Rack Rate (set by management)
4-sharing     +  Non-AC    +  With Food   =  ₹5,500/month
4-sharing     +  Non-AC    +  Without     =  ₹4,000/month
4-sharing     +  AC        +  With Food   =  ₹7,000/month
4-sharing     +  AC        +  Without     =  ₹5,500/month
2-sharing     +  AC        +  With Food   =  ₹10,000/month
2-sharing     +  AC        +  Without     =  ₹8,000/month
```

- Both rack rates are always entered manually by Owner/Manager
- The difference between with-food and without-food rates is owner's discretion — no formula
- Changing a room's category or rack rates does not retroactively affect existing residents' contracted rents

### Room Status Rules
- **Available** — at least one bed is vacant
- **Occupied** — all beds filled
- **Reserved** — beds reserved but not yet checked in
- **Maintenance** — room temporarily unavailable

---

## Module 4: Bed Management

### Bed Information
- Bed Number (e.g., 101-A, 101-B)
- Room reference
- Rack rent amount (inherited from room rack rate by default, can be overridden per bed)
- Status (Available / Occupied / Reserved / Maintenance)

### Per-Bed Rack Rate Override
In most cases all beds in a room share the same rack rates. However, management can override the rack rates per bed for edge cases:

```
Room 201 — 4-sharing | AC
  Rack Rate (with food)    ₹7,000  |  Rack Rate (without food)  ₹5,500

  Bed 201-A   With food ₹7,000 / Without food ₹5,500  (standard)
  Bed 201-B   With food ₹7,000 / Without food ₹5,500  (standard)
  Bed 201-C   With food ₹6,500 / Without food ₹5,000  (overridden — windowless corner bed)
  Bed 201-D   With food ₹7,000 / Without food ₹5,500  (standard)
```

- Override is optional — most beds inherit the room's rack rates
- Override does not affect other beds in the same room
- Existing contracted rents are never retroactively changed by a rack rate override

---

## Module 5: Resident Management

### Resident Profile

**Personal Information**
- First Name, Last Name
- Gender
- Date of Birth
- Phone Number
- Email

**Address Information**
- Permanent Address
- Current Address (before joining)

**Emergency Contact**
- Name, Relation, Phone Number

**Identity Documents**
- Aadhaar Number + Upload
- PAN Card + Upload
- Passport *(optional)*
- Employee ID *(optional)*
- Student ID *(optional)*

**Resident Status Lifecycle**
```
Inquiry → Reserved → Active → Notice Period → Vacated
                    ↓                       ↘ Blacklisted
                    └──────────────────────→ Absconded → Blacklisted
```

---

## Module 6: Admission Management

### Admission Workflow
```
Inquiry
  → Property Visit
    → Reservation (bed held, advance collected)
      → Admission (documents, billing setup)
        → Check-In (bed allocated, status → Active)
```

### Admission Details Captured
- Joining Date
- Billing Mode (Monthly / Weekly / Daily)
- Expected Stay Duration
- Selected Room and Bed
- Contracted Sharing Type (e.g., 4-sharing)
- Contracted Room Category (AC / Non-AC — snapshot at time of admission)
- Food Preference (With Food / Without Food)
- Contracted Rent (rack rate corresponding to food preference — snapshotted at admission)
- Advance Amount Collected (e.g., ₹1,500)
- First Month Billing Note (partial month — amount set manually by management)

> **Why snapshot contracted rent at admission?** The room's rack rates may change after the resident moves in. The contracted rent locks in the agreed price regardless of future rate changes.

---

## Module 7: Bed Allocation & Temporary Allocation

### Standard Allocation
```
Resident → Room → Bed
```

### Temporary Allocation
Handles the scenario where a resident's preferred room type is unavailable and they are placed in a different room temporarily, **at their contracted price**.

**Allocation Record Fields**
- `allocated_bed` — actual bed currently assigned
- `contracted_room_type` — sharing type agreed at admission (e.g., 4-sharing)
- `contracted_room_category` — AC / Non-AC as agreed at admission
- `contracted_rent` — price agreed at admission (e.g., ₹6,500)
- `actual_room_type` — current room sharing type (e.g., 3-sharing)
- `actual_room_category` — AC / Non-AC of the temporary room
- `is_temporary` — true / false
- `temporary_since` — date temporary allocation started
- `expected_move_date` — anticipated date of move to correct room *(optional)*
- `temporary_note` — free text (e.g., "4-sharing AC unavailable, placed in 3-sharing AC temporarily")

**Billing Rule**
> Invoices always use `contracted_rent`, never the rack rate of the temporary room.

**Owner Dashboard Flag**
- All temporarily allocated residents shown in a dedicated list
- Badge shown on resident card:
  ```
  ⚠ Temporary Allocation
  Currently in: Room 202 (4-sharing | AC)
  Contracted for: 4-sharing | AC @ ₹6,500/month
  Since: 01 Jun 2026
  ```
- When a matching room (same sharing type + same AC/Non-AC category) becomes available, system suggests moving flagged residents *(V2 automation)*

### Transfer Management
When a resident moves from one bed/room to another:
- Previous room and bed
- New room and bed
- Reason for transfer
- Transfer date
- `previous_rent` — contracted rent before transfer
- `new_rent` — contracted rent after transfer
- `rent_effective_date` — determined by the property's **Room Transfer Rent Timing** setting (Immediately or Next Billing Cycle)
- Recorded by (staff member)

> Billing behaviour on transfer is governed by the property-level setting defined in **Module 2B — Property Settings**.

---

## Module 8: Resident Discount Management

### When Discounts Apply
- Long-term resident loyalty
- Referral (referred a new resident)
- Corporate / company tie-up
- Negotiated at admission
- Seasonal / festival offer
- Staff or owner's known person

### Discount Record Fields
- `discount_type` — Fixed (₹) / Percentage (%)
- `discount_value` — amount or percentage
- `discount_reason` — Loyalty / Referral / Corporate / Negotiated / Seasonal / Other
- `discount_note` — free text (e.g., "Friend of owner, approved verbally")
- `discount_valid_from` — start date
- `discount_valid_until` — end date (null = indefinite)
- `approved_by` — Owner or Manager who approved

### Discount Scope
- Discount is applied at the **resident-allocation level** — two residents in the same room can have different discounts
- Discount is applied on top of `contracted_rent`, not on rack rate

### Invoice Calculation with Discount
```
Contracted Rent        ₹6,000
Discount               ₹500 (Loyalty — approved by Rahul)
──────────────────────────────
Payable Rent           ₹5,500
```

Both lines shown on invoice so resident sees the benefit.

### Combined Scenario (Temporary Allocation + Discount)
```
Contracted Room     4-sharing | AC @ ₹6,500/month
Temporary Room      3-sharing | AC (no extra charge)
Loyalty Discount    10% = ₹650
────────────────────────────────────────────────────
Payable Rent        ₹5,850
```

### Discount Reports
- Total discount given this month across all residents
- Number of residents currently on discount
- Discount breakdown by reason type

---

## Module 9: Rent & Billing

### Billing Modes
| Mode | Description | Use Case |
|------|-------------|----------|
| Monthly | Charged once per month | Standard PG residents |
| Weekly | Charged per week | Short-stay guests |
| Daily | Charged per day | Very short-stay / transient guests |

### Food Charges

Each room has **two separate rack rates** set by management — one with food included, one without. These are independent prices, not a simple addition. The resident chooses their food preference at admission and is billed at the corresponding rate.

**Room-level rack rate configuration:**
```
Room 201 — 4-sharing | AC
  Rack Rate (with food)      ₹7,000/month
  Rack Rate (without food)   ₹5,500/month
```

> The without-food rate is not necessarily rack-rate-minus-food-charge. It is a separate price entirely, set by the owner. For example, with food may be ₹7,000 but without food may be ₹5,500 — a difference of ₹1,500, which is the owner's choice, not a formula.

**Invoice with food:**
```
Accommodation + Food (Monthly)    ₹7,000
──────────────────────────────────────────
Total                             ₹7,000
```

**Invoice without food:**
```
Accommodation (Monthly)           ₹5,500
──────────────────────────────────────────
Total                             ₹5,500
```

**Resident fields at admission:**
- `food_preference` — With Food / Without Food
- `contracted_rent` — set to the corresponding rack rate at admission time (snapshotted)

**Changing food preference mid-stay:**
- Resident can request to switch food preference
- Owner/Manager updates the preference
- New contracted rent applies from next billing cycle (follows the same rule as room transfer timing)
- Change is recorded in the activity timeline

### Invoice Components
- Accommodation Rent (based on contracted rent)
- Food Charges *(if applicable)*
- Electricity Charges *(if applicable)*
- Water Charges *(if applicable)*
- Laundry Charges *(if applicable)*
- Add-on Service Charges *(Diet Food, Gym/Play Area — future, see note below)*
- Additional Charges *(free text, any ad-hoc charge)*
- Discount *(shown as negative line item)*
- Late Payment Penalty *(if applicable — added automatically based on property settings after grace period)*
- **Total Payable**

> Late payment penalty behaviour is governed by the property-level setting in **Module 2B — Property Settings**.

### Future-Proofing: Resident Add-On Services

**Not implemented in MVP.** However, the system is designed to support optional chargeable add-on services per resident in a future version — specifically:

- **Diet Food** — specialised meal plan (different from the standard food charge)
- **Gym / Play Area Access** — optional facility access with a monthly charge

**Why it's noted here and not just in the roadmap:**

The data model for add-ons must be considered now to avoid a painful migration later. Specifically:

- The `resident_admission` record should have a reserved `addons` JSON field (empty array `[]` in MVP) that future versions can populate without a schema change
- The invoice generation logic should be built to iterate over a list of charge line items rather than hardcoding fixed fields — so adding a new charge type in future requires zero changes to the invoice engine
- The admission workflow UI should be built with an "Add-on Services" section that is simply hidden/disabled in MVP, not absent

**Future add-on record structure (for reference when implementing):**
```
addon_id
resident_id
addon_type          → diet_food / gym / play_area / (extensible)
addon_name          → display name on invoice
charge_amount       → ₹ per billing period
charge_frequency    → monthly / weekly / daily
opted_in_date
opted_out_date      → null if still active
```

**Future invoice line item:**
```
Accommodation Rent     ₹5,000
Food Charges           ₹2,000
Diet Food Add-on       ₹1,500
Gym Access             ₹800
──────────────────────────────
Total                  ₹9,300
```

### Partial Month Billing
- First month invoice amount is **set manually by management**
- System provides a free-text note field: e.g., "Partial month — joined 15th June"
- No automated pro-rata calculation — management has full control
- Subsequent months are billed at full contracted rent

### Invoice Status
- **Draft** — created but not issued to resident
- **Issued** — sent to resident
- **Paid** — fully settled
- **Partially Paid** — one or more partial payments received, balance remaining
- **Overdue** — past due date, unpaid or partially paid

### Invoice Generation
- Monthly invoices generated manually (trigger by Owner/Accountant) for MVP
- Bulk generation for all active residents in a property in one click
- Weekly/daily invoices generated on check-out for short-stay residents

---

## Module 10: Payment Management

### Payment Recording
All resident payments are recorded **manually** by the Owner/Accountant.
> Razorpay is NOT used for resident payments. Owners collect via UPI, cash, or bank transfer and record in the system.

### Payment Modes (for manual recording)
- UPI
- Cash
- Bank Transfer
- Card
- Cheque

### Partial Payment Support
- Management decides whether to accept partial payment
- Multiple partial payments can be recorded against one invoice
- Each partial payment is a separate record with date, amount, mode, and recorded-by

**Example:**
```
Invoice Amount         ₹5,000
Payment 1 (1 Jun)      ₹2,000  — UPI
Payment 2 (10 Jun)     ₹2,000  — Cash
──────────────────────────────
Balance Due            ₹1,000
Invoice Status         Partially Paid
```

- Invoice status automatically updates based on payments received
- Outstanding balance visible on resident card and financial dashboard
- No auto-penalty for late payment in MVP — management handles manually

### Payment Record Fields
- Invoice reference
- Amount paid
- Payment date
- Payment mode
- Transaction reference / note *(optional)*
- Recorded by (staff member)

### Payment Features
- Auto-generated receipt after payment recording
- Full payment history per resident
- Outstanding dues view across all residents

---

## Module 11: Security Deposit & Advance Management

### Advance Collected at Admission
- A fixed advance amount is collected at the time of admission (e.g., ₹1,500)
- This is separate from the security deposit concept
- Tracked as: `advance_amount`, `advance_collected_date`, `advance_mode`

### Notice Period
- Standard notice period: **1 month**
- Resident informs management of intent to vacate
- Rent for the notice period month is due as normal

### Vacating Workflow
```
Resident gives notice
  → Notice Period Start date recorded
  → Expected Vacate Date = Notice Date + 1 month
  → Rent for notice period month invoiced as normal
  → On vacate date: Management inspects room
    → Management enters maintenance deduction amount
      → System calculates: Refund = Advance - Maintenance Deduction
        → Refund recorded (mode + date)
          → Resident status → Vacated
            → Bed status → Available
```

### Deposit/Advance Record Fields
- `advance_amount` — amount collected at admission
- `advance_collected_date`
- `advance_mode` — UPI / Cash / Bank Transfer
- `notice_given_date`
- `expected_vacate_date` — auto-calculated (notice date + 1 month)
- `actual_vacate_date`
- `maintenance_deduction` — entered by management after room inspection
- `maintenance_deduction_note` — reason (e.g., "Wall damage, missing chair")
- `refund_amount` — auto-calculated (advance - deduction)
- `refund_date`
- `refund_mode`
- `refund_note`
- `settled_by` — staff member who closed the exit

### Deduction Rules
- Deduction amount is **decided by management** — no fixed formula
- Deduction cannot exceed advance amount
- Management can choose to refund full advance (zero deduction)
- All deductions recorded with notes for audit trail

---

### Absconded Resident Workflow

An absconded resident is one who has **left without notice, without settling dues, and without returning the key/access** — as opposed to a normal vacate which follows the notice period process.

**Workflow:**
```
Management marks resident as Absconded
  → Absconded date recorded
  → Bed status → Available (freed immediately)
  → All unpaid invoices remain outstanding (not written off)
  → Advance forfeited — applied against outstanding dues
  → Remaining outstanding dues recorded as irrecoverable (management decision)
  → Resident status → Absconded
  → Resident automatically flagged for Blacklisting
  → Management confirms Blacklist → status → Blacklisted
```

**Absconded Record Fields**
- `absconded_date` — date management marked them as absconded
- `last_seen_date` — last known date they were at the property *(optional)*
- `absconded_note` — free text (e.g., "Left without notice, room found empty on 10 Jun")
- `advance_forfeited` — true / false (advance is not refunded)
- `advance_applied_to_dues` — amount of advance applied against outstanding balance
- `remaining_dues` — outstanding balance after advance adjustment
- `dues_recovery_status` — Outstanding / Partially Recovered / Written Off
- `dues_written_off_by` — Owner/Manager who approved write-off
- `dues_written_off_note` — reason for write-off
- `marked_by` — staff member who triggered the absconded status

**Financial Handling:**
```
Outstanding Dues (unpaid invoices)    ₹8,000
Advance Held                          ₹1,500
──────────────────────────────────────────────
Advance forfeited, applied to dues    ₹1,500
Remaining Unrecovered Dues            ₹6,500  → marked as Written Off or Outstanding
```

**Blacklisting:**
- Absconded residents are flagged for blacklisting automatically
- Owner must explicitly confirm blacklisting — it is not automatic
- Once blacklisted, the resident's phone number and Aadhaar/ID are stored in the tenant's blacklist
- If a blacklisted person attempts to re-register at any property under the same tenant, the system shows a warning
- Blacklist flag is visible across all properties of the tenant

**Dashboard Indicators:**
- Absconded residents appear in a dedicated **Absconded** section in the resident list
- Badge on resident card: `⚠ Absconded — ₹6,500 dues unrecovered`
- Separate report: Absconded residents with total unrecovered dues

**Important distinctions vs normal vacate:**
| Factor | Normal Vacate | Absconded |
|--------|--------------|-----------|
| Notice given | Yes — 1 month | No |
| Dues settled | Yes (ideally) | No |
| Advance | Refunded minus deductions | Forfeited, applied to dues |
| Bed freed | On vacate date | Immediately on marking |
| Blacklisted | Only if manually done | Flagged automatically, confirmed by owner |

---

## Module 12: Complaint Management

### Complaint Categories
- Electrical
- Plumbing
- Internet / WiFi
- Housekeeping
- Security
- Furniture
- Other

### Complaint Workflow
```
Open → Assigned → In Progress → Resolved → Closed
```

### Features
- Photo/file upload with complaint
- Comments thread (resident + staff)
- Priority levels (Low / Medium / High / Urgent)
- SLA tracking *(V2)*

---

## Module 13: Visitor Management

### Visitor Record
- Visitor Name
- Mobile Number
- Resident being visited
- Purpose of visit
- Entry Time
- Exit Time

### Features
- Visitor approval by Warden/Receptionist
- Visitor history per resident
- QR Visitor Pass *(V2)*

---

## Module 14: Attendance Management *(V2)*
- Manual check-in/check-out marking
- QR Code based attendance *(V2)*
- RFID / Biometric Integration *(V3)*

---

## Module 15: Maintenance Management *(V2)*

### Request Types
- AC Repair, Fan Repair, Plumbing, Furniture, Electrical, Other

### Features
- Vendor assignment
- Cost tracking
- Maintenance history per room/property

---

## Module 16: Inventory Management *(V3)*

### Assets Tracked
- Beds, Mattresses, Chairs, Tables, Water Coolers, Washing Machines

### Tracked Per Asset
- Purchase Date, Condition, Repair History

---

## Module 17: Staff Management *(V2)*

### Staff Details
- Name, Role, Contact, Salary, Shift

### Features
- Attendance tracking
- Payroll records
- Leave requests

---

## Module 18: Notifications

### MVP (Email only)
- Welcome email on signup
- Trial expiry reminders (Day 45, Day 55)
- Invoice generated notification to resident
- Payment receipt to resident

### V2
- SMS for due reminders and alerts
- WhatsApp for payment receipts and notices
- Push notifications (mobile app)

---

## Module 19: Reporting & Analytics

### Occupancy Dashboard
- Total beds / Occupied / Vacant / Reserved (per property and overall)
- Occupancy % trend over time
- List of temporarily allocated residents *(with flag)*

### Financial Dashboard
- Revenue collected this month
- Outstanding dues (total + per resident)
- Discounts given this month
- Advance/deposit balance held

### Resident Reports
- Active residents list
- Residents in notice period
- Recently vacated
- Residents on discount

### Complaint Reports *(V2)*
- Open tickets
- Average resolution time

---

## Module 20: Subscription Management

### Plan Management
- Current plan and usage (properties used vs. allowed)
- Upgrade / downgrade flow
- Billing history and invoices from platform
- Razorpay webhook handling for payment success/failure

### Subscription States
- Trial (Day 0–60)
- Active
- Payment Failed (grace period — 5 days)
- Suspended (login blocked, data intact)
- Cancelled (data retained 30 days)

---

## Module 21: Audit Logs

Track every critical action with:
- User who performed the action
- Action type
- Before and after values *(for edits)*
- Timestamp
- IP Address

### Audited Actions (examples)
- Resident created / edited / vacated
- Resident marked as Absconded (with note)
- Resident Blacklisted / Blacklist confirmed
- Outstanding dues written off (who approved, amount, reason)
- Room allocated / transferred
- Invoice created / edited / deleted
- Payment recorded / deleted
- Discount applied / modified
- Advance deduction entered
- Late payment penalty applied / waived (with reason)
- Property setting changed (before + after value recorded)
- Plan upgraded / downgraded
- User role changed

---

## Module 22: Activity Timeline

Per-resident chronological event log:

```
Inquiry Received              01 Jan 2026
Room Reserved                 03 Jan 2026
Admission Completed           05 Jan 2026
Checked In — Room 201B        05 Jan 2026
Invoice Generated             01 Feb 2026
Partial Payment ₹2,000        05 Feb 2026
Remaining Paid ₹3,000         10 Feb 2026
Transferred to Room 305A      15 Feb 2026
Complaint Raised              20 Feb 2026
Invoice Generated             01 Mar 2026
Invoice Overdue               10 Mar 2026
Marked Absconded              15 Mar 2026  ← last seen 12 Mar, room found empty
Advance Forfeited ₹1,500      15 Mar 2026  ← applied against dues
Dues Written Off ₹6,500       20 Mar 2026  ← approved by Owner
Blacklisted                   20 Mar 2026
```

---

## Module 23: Data Export

Supported Formats:
- CSV
- Excel
- PDF

Available For:
- Resident list
- Payment history
- Outstanding dues
- Occupancy report

---

# 8. Key Business Rules Summary

| Scenario | Rule |
|---------|------|
| Absconded — bed release | Bed freed immediately on marking, no notice period |
| Absconded — advance | Forfeited, applied against outstanding dues |
| Absconded — remaining dues | Recorded as outstanding; owner can write off with mandatory note |
| Absconded — blacklisting | Auto-flagged, but owner must explicitly confirm blacklist |
| Blacklist scope | Applies across all properties under the same tenant |
| Blacklist re-entry warning | System warns if blacklisted ID/phone attempts re-registration |
| Food preference change mid-stay | New contracted rent applies from next billing cycle; recorded in activity timeline |
| Room category change | Does not auto-update rack rate — management must update manually |
| Rack rate change on room | Does not retroactively affect existing residents' contracted rents |
| Contracted room category | Snapshotted at admission — changes to room after admission do not affect the resident's contract |
| Per-bed rack rate override | Optional — most beds inherit room rack rate; override allowed for individual beds |
| Temporary allocation matching | Match is on sharing type + AC/Non-AC category |
| Temporary allocation billing | Always bill at contracted rent, not rack rate of temporary room |
| Discount calculation | Applied on contracted rent, not rack rate |
| Partial month billing | Amount set manually by management |
| Partial payment | Accepted at management's discretion, recorded per payment |
| Notice period | 1 month standard |
| Advance deduction | Decided by management at exit, with mandatory note |
| Refund calculation | Advance Amount − Maintenance Deduction |
| Room transfer rent timing | Configured per property — Immediately or Next Billing Cycle |
| Shared invoices | Never — each resident always has their own invoice |
| Late payment penalty | Configured per property — No Penalty / Fixed / Percentage |
| Penalty grace period | Configurable per property (default: 5 days) |
| Penalty waiver | Management can waive per invoice with mandatory note; recorded in audit log |
| Active resident definition | Status = Active or Notice Period — all other statuses excluded from count |
| Plan limit — properties | Hard block at configured limit; Super Admin can override per tenant |
| Plan limit — residents | Hard block at configured active resident count per property |
| Limit values | Configurable by Super Admin — no code change needed; finalised at marketing launch |
| Payment failure (subscription) | 5-day grace period, then account suspended |
| Razorpay usage | Platform subscription billing only — not resident payments |

---

# 9. Mobile Applications *(V2)*

## Resident App (Flutter)
- View profile and billing history
- View and download invoices/receipts
- Raise and track complaints
- Submit visitor requests
- View notices

## Staff App (Flutter)
- Attendance marking
- Complaint handling
- Resident search

---

# 10. API Requirements

## API Style
REST API (GraphQL in V3)

## API Groups

```
/api/v1/auth/
/api/v1/tenants/
/api/v1/subscriptions/
/api/v1/properties/
/api/v1/properties/{id}/settings/
/api/v1/floors/
/api/v1/rooms/
/api/v1/beds/
/api/v1/staff/
/api/v1/staff/assignments/
/api/v1/residents/
/api/v1/admissions/
/api/v1/allocations/
/api/v1/invoices/
/api/v1/payments/
/api/v1/deposits/
/api/v1/discounts/
/api/v1/complaints/
/api/v1/visitors/
/api/v1/reports/
/api/v1/audit-logs/
```

---

# 11. Non-Functional Requirements

## Performance
- API response time < 500ms (p95)
- Support 1,000+ concurrent users

## Availability
- 99.9% uptime SLA

## Scalability
- Horizontal scaling via Docker + AWS
- Multi-region support *(V3)*

## Security
- HTTPS enforced everywhere
- Bcrypt password hashing
- JWT with short expiry + refresh tokens
- Row-level tenant isolation (PostgreSQL RLS)
- Audit logging on all critical actions
- Rate limiting on all API endpoints
- CSRF protection
- File upload validation and virus scanning *(V2)*

---

## Internationalisation (i18n)

The platform must support multiple languages from the ground up. The target languages are:

| Language | Script | Region |
|----------|--------|--------|
| English | Latin | Default / All |
| Hindi | Devanagari | North India |
| Telugu | Telugu | Andhra Pradesh, Telangana |
| Tamil | Tamil | Tamil Nadu |
| Malayalam | Malayalam | Kerala |

> Additional languages can be added later without architectural changes, provided the i18n foundation is built correctly from the start.

### What Gets Translated

**UI Layer (frontend + mobile)**
- All labels, buttons, headings, and navigation
- Form field names and placeholder text
- Error messages and validation text
- Status labels (Active, Vacated, Absconded, etc.)
- Notification and email templates
- Invoice and receipt templates (PDF output in the selected language)

**What Does NOT Get Translated**
- Data entered by users (resident names, addresses, notes — stored as-is)
- Property names and room numbers (user-defined content)
- Audit log entries (stored in English for consistency)

### Language Selection

**Per User:**
- Each user (Owner, Manager, Resident) selects their preferred language at signup or from profile settings
- Language preference is stored per user account — not per tenant
- Language can be changed at any time from profile settings
- Default language: English

**Per Tenant (optional override):**
- Owner can set a default language for their tenant account
- New staff/resident accounts under that tenant default to the tenant language
- Individual users can still override to their own preference

### Architecture Requirements

**Frontend (Next.js)**
- Use `next-i18next` or `react-i18next` for UI string management
- All UI strings must be externalised into language JSON files from day one — no hardcoded strings anywhere in the codebase
- Language files organised by module: `auth.json`, `residents.json`, `billing.json`, etc.
- RTL support not required for current language set (all target languages are LTR)
- Font stack must include support for Indic scripts — use Google Fonts (Noto Sans family covers all target scripts)

**Backend (Django)**
- Use Django's built-in `django.utils.translation` (gettext) for any server-generated strings
- Email and notification templates stored as translatable template files per language
- API responses return data only — all UI labels and strings are handled client-side
- `Accept-Language` header respected by the API for any server-rendered content (e.g. PDF invoices)

**Database**
- User language preference stored as: `language_code` — ISO 639-1 code (`en`, `hi`, `te`, `ta`, `ml`)
- No translation tables needed — translations live in frontend language files, not the database
- User-entered content (names, notes, addresses) stored in Unicode (UTF-8) — PostgreSQL handles all Indic scripts natively

**PDF / Invoice Generation**
- Invoice and receipt PDFs must render correctly in the selected language
- Use a PDF library that supports Unicode and Indic fonts (e.g. WeasyPrint with Noto fonts)
- Language for PDF follows the generating user's language preference

### MVP Approach

Full translation of all languages in MVP is not required — but the **architecture must be i18n-ready from day one**.

| Phase | Language Support |
|-------|----------------|
| MVP | English fully implemented. i18n architecture in place (all strings externalised). Language switcher UI built but only English active. |
| V2 | Hindi and Telugu added |
| V3 | Tamil and Malayalam added |

> **Critical rule for developers:** No hardcoded UI strings anywhere. Every label, message, and status text must go through the i18n translation function from the first line of code. Adding a new language later should require only adding a new JSON file — zero code changes.

---

# 12. Technology Stack

## Backend
- Python 3.12
- Django 5.x
- Django REST Framework
- Celery (background tasks)
- Redis (cache + task queue)

## Database
- PostgreSQL 16 (with Row-Level Security)

## Storage
- AWS S3 (document uploads, identity docs)

## Frontend
- Next.js 14
- TypeScript
- Tailwind CSS
- next-i18next (internationalisation)
- Noto Sans font family (Indic script support)

## Mobile *(V2)*
- Flutter

## Payments
- Razorpay (subscription billing only)

## Infrastructure
- Docker + Docker Compose
- Nginx (reverse proxy)
- AWS (EC2, RDS, S3, SES)
- GitHub Actions (CI/CD)

---

# 13. MVP Scope (Version 1)

## Phase 1 — The Skeleton (Weeks 1–6)
*Goal: One owner can set up their property and place residents in beds*

- [ ] Tenant onboarding and 60-day trial activation
- [ ] Email/password auth + OTP login
- [ ] Role-based access (Super Admin, Owner, Manager, Receptionist, Resident)
- [ ] Manager multi-property assignment by Owner
- [ ] i18n architecture set up — all strings externalised, language switcher built (English only active)
- [ ] Property → Floor → Room → Bed setup
- [ ] Property Settings panel (Room Transfer Timing, Late Payment Penalty, Grace Period)
- [ ] Resident profile creation
- [ ] Admission workflow (Inquiry → Check-In)
- [ ] Bed allocation with temporary allocation support
- [ ] Occupancy dashboard

## Phase 2 — The Money (Weeks 7–10)
*Goal: Owner can track who has paid and who hasn't*

- [ ] Invoice generation (monthly, manual trigger)
- [ ] Partial month billing (manual first-invoice amount)
- [ ] Discount management per resident
- [ ] Manual payment recording with partial payment support
- [ ] Payment receipts
- [ ] Security deposit / advance tracking
- [ ] Vacating workflow with deduction and refund
- [ ] Outstanding dues dashboard

## Phase 3 — Operations & Launch (Weeks 11–13)
*Goal: Polish, complaints, visitors, subscription gate*

- [ ] Complaint management (basic workflow)
- [ ] Visitor management
- [ ] Razorpay subscription integration (trial → paid)
- [ ] Plan limit enforcement (property count gate)
- [ ] Email notifications (welcome, invoice, receipt, trial expiry)
- [ ] Audit logs
- [ ] Activity timeline per resident
- [ ] Basic data export (CSV)

---

# 14. Future Roadmap

## Version 2
- Flutter mobile apps (Resident + Staff)
- WhatsApp + SMS notifications
- Staff management and payroll
- Maintenance management
- Attendance management (manual + QR)
- Advanced financial reports
- Inventory management
- **Resident Add-On Services** — Diet Food and Gym/Play Area as optional chargeable add-ons per resident, billed as separate invoice line items
- **Hindi and Telugu language support**

## Version 3
- Biometric / RFID integration
- White-label hosting for enterprise clients
- AI-powered analytics and occupancy predictions
- QR-based visitor passes
- GraphQL API
- **Tamil and Malayalam language support**

## Version 4
- Dynamic pricing engine
- Predictive occupancy analysis
- Marketplace integrations
- Multi-country and multi-currency support

---

*Document prepared based on product planning discussions — June 2026*
