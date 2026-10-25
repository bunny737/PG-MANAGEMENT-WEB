# SEO keyword map (B0 discovery)

Status: **draft for owner approval**, 2026-10-25. No slug in this file is final until the owner signs off, and `frontend/src/features/marketing/content/landing.ts` does not exist yet. Plan: [frontend-plan.md §12.9](../frontend-plan.md).

Rule: one primary query cluster per URL, and a candidate that fails the intent or truthfulness check is dropped or merged rather than padded into a page.

## How this was gathered, and what it cannot tell us

- **Method:** 12 manual searches on 2026-10-25 with a US-only web search tool, reading result titles and snippets to judge *intent* (software vendors versus PG listings versus institutional ERPs) and to list competitors.
- **Not available:** search volumes (Google Keyword Planner), Search Console impressions (the domain is not verified or live yet), and India-localised result pages. Everything below about *demand* is therefore a hypothesis. Intent and competitor findings are solid; volume claims are not made.
- **Before any page is written, the owner should:** (1) verify the Search Console domain property (docs/deployment.md §9), (2) export Keyword Planner volumes for India for the clusters below, and (3) confirm the claims flagged "check" in the last column of the page table.

## What the results show

| Query tried | Intent | What ranks |
|---|---|---|
| PG management software India | Software | Vendor pages and blog posts: RentOk (dominant, many near-duplicate "best … 2023" pages), SpaceBasic, HarGharPG |
| hostel management software India | Software, mixed audience | RentOk (PG/hostel owners), SourceForge directory (lists TrackMyPG from ₹299/month), plus institutional systems |
| PG rent management app for owners | Software, app-store heavy | RentOk, StayPe (App Store), PayRent (App Store) |
| paying guest management software rent invoice reminders | Software | TrackMyPG, GoPGMS, BigBHK, PayRent, RentOk |
| PG owner software multiple properties track vacant beds | Software | RentOk articles on bed-level occupancy and multi-property dashboards, StayPe |
| PG complaint management visitor management app | Software, fragmented | SpaceBasic complaint pages; generic visitor-management apps (no PG-specific product) |
| ladies PG management software | Software, **not distinct** | The same generic PG software pages. Nothing is written for women-only PGs |
| coliving management software India | Software, **thin for India** | An Odoo module, a global coliving-software roundup, StayPe, and coliving *operators* (Colive) that are not software |
| PG management software Hyderabad / Bangalore | Software, **national pages** | The same national vendor pages. No vendor ranks a city-specific page |
| student hostel management system software | Software, **institutional** | School and university ERPs: SpaceBasic campus housing, Creatrix, MasterSoft, Digii, Skolaro |

Competitors to know: RentOk, SpaceBasic, HarGharPG, StayPe (formerly QuickStay), TrackMyPG, GoPGMS, PayRent, BigBHK. Most of their content is vendor marketing, and the RentOk posts are dated 2023, so fresh, specific, accurate pages are a realistic way in.

## Decisions

### Build first (wave 1): three solution pages

The home page already owns **"PG management software"** (its title and description target it), so no new page competes for that cluster.

| Slug (proposed) | Primary cluster | Secondary terms | Intent note | Features it may claim (ownerWeb = `available` today) | Check before writing |
|---|---|---|---|---|---|
| `/solutions/pg-rent-tracking` | PG rent management app | paying guest rent invoice, PG rent software, rent due tracking | Software, App Store listings rank, so an "app" angle helps | billing, payments, discounts, expenses, reports | Copy must say *invoices and payment tracking*; PGLive never collects rent (invariant: Razorpay is subscriptions only). **No claim of automatic rent reminders**: no marketing copy or feature entry supports it today |
| `/solutions/hostel-management-software` | hostel management software | hostel software India, private hostel management | Mixed audience: copy must say plainly it is for **privately run PGs and hostels, not school or university campuses**, or it attracts the wrong visitors | residents, billing, payments, visitors, staff, reports, dashboard | Visitor log is `available`; complaints is only `preview` and must not headline |
| `/solutions/pg-bed-occupancy` | track vacant beds across PG properties | PG occupancy software, multi-property PG software, vacancy tracking | Software, RentOk articles show the demand shape | dashboard (beds occupied and vacant, one property or all), residents | `allocations` (bed transfers) is `comingSoon`: describe occupancy *visibility*, never transfers. Confirm the dashboard figures are per bed before claiming bed-level |

Cannibalisation check: the three clusters are distinct (money, building type, vacancy). The home page keeps the generic cluster.

### Not now, with the reason

| Candidate | Decision | Why | Revisit when |
|---|---|---|---|
| ladies PG management software | **Merge into FAQs**, no page | Results are generic PG software, so there is no distinct software intent, and a page would mostly attract accommodation searchers. PGLive does have a property-level gender preference (`Property.gender_preference`), so a FAQ on the hostel and home pages can answer "can I run a ladies-only PG?" truthfully | Search Console shows real impressions for this phrasing |
| coliving management software | **Skip** | Ambiguous, global, and not India-specific in the results; the product is a PG and hostel tool, not a coliving platform | The product adds coliving-specific features |
| student hostel management | **Skip, do not merge** | The results are institutional ERPs for schools and universities (a different buyer and a different product). Targeting it would misdescribe PGLive and compete head-on with campus vendors | Never, unless an institutional product is built |
| PG complaint management / visitor management | **Wait** | No PG-specific rival product ranks apart from SpaceBasic, which is an opening, but complaints is only `preview` on the owner web, so a page cannot honestly headline it | `complaints` becomes `available` in `content/features.ts` |
| City pages (Hyderabad, Bengaluru, Chennai, Pune) | **None in wave 1** | No vendor ranks a city-specific page, which suggests low city-specific *software* demand, though this is untested without volumes. Without verified local facts, unique FAQs and a distinct worked example (the acceptance rule in the plan), city pages would be doorway pages | Search Console or Keyword Planner shows city-qualified software queries, **and** local facts with sources can be written. Hyderabad is the likeliest first city given Telugu support, but that is a product fact, not a search fact |

## Differentiators the copy can use (all from shipped features)

- Rent, discounts, electricity and water appear as separate invoice lines (billing).
- Part payments and UPI, cash, bank transfer, card and cheque are recorded (payments).
- Discounts with a reason and validity window (discounts).
- English and Telugu interface today (languages). The pages themselves stay English-only for indexing.
- One dashboard across one or all properties (dashboard).

## Open questions for the owner

1. Approve, change or drop the three wave-1 slugs.
2. Export Keyword Planner volumes for India for the six clusters above (or approve using Search Console data after a few weeks of being live, which is slower but free).
3. Is a 2026 "PG software comparison" page wanted? Competitors' comparison posts rank, but a comparison needs verified competitor facts and is not in the plan. Not proposed here.
4. Confirm whether rent reminders exist or are planned, so the rent-tracking page does not have to omit them.

## Next step once approved

PR 4: `landing.ts` with the approved slugs (`lastReviewed`, feature ids, primary cluster), the two hub pages, the leaf template, the `marketingPaths.ts` wiring, the sitemap entries, the footer links, and per-slug 404 probes in `scripts/seo-smoke.mjs`.
