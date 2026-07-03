# Module: Allocations & Transfers

> Keep this file in sync with the code AT ALL TIMES.
> If the code and this file disagree, this file is wrong — fix it in the same commit.

**Status:** Done
**Phase:** 1
**PRD reference:** Module 7 (Bed Allocation & Temporary Allocation)
**Depends on:** 05
**Blocks:** 07, 08

## Purpose
Track where each active resident physically sleeps *right now* (the
Allocation), flag temporary placements (billed at contracted rent
regardless — invariant 3), and record every bed/room move as an
append-only Transfer whose new-rent timing follows the property's Module 2B
"Room Transfer Rent Timing" setting.

## Data model (as-built)

```
Table: allocations                              (RLS enforced, app: apps.residents)
  id                    uuid PK
  tenant_id             uuid              (RLS)
  resident              OneToOne -> residents.Resident (PROTECT)
  allocated_bed         FK -> properties.Bed (PROTECT)   ← current physical bed

  # The contracted deal — copied from Admission at check-in, changed only by
  # a permanent transfer. Never auto-recomputed from the room (invariant 2).
  contracted_sharing_type   1 | 2 | 3 | 4
  contracted_room_category  ac | non_ac
  contracted_rent            decimal(12,2)

  is_temporary          bool (default false)
  temporary_since       date, null
  expected_move_date    date, null
  temporary_note        text, blank
  created_at / updated_at
  # actual_sharing_type / actual_room_category are derived from
  # allocated_bed.room in the serializer — never stored (can't drift).

Table: transfers                                (RLS enforced, app: apps.residents)
  id                    uuid PK
  tenant_id             uuid              (RLS)
  resident              FK -> residents.Resident (PROTECT)
  previous_bed          FK -> properties.Bed (PROTECT)
  new_bed               FK -> properties.Bed (PROTECT)
  is_temporary          bool
  reason                text, blank
  transfer_date         date
  previous_rent         decimal(12,2)
  new_rent              decimal(12,2)
  rent_effective_date   date              ← from Module 2B setting
  recorded_by           FK -> users, null (SET_NULL)
  created_at / updated_at
```

## API endpoints
```
GET      /api/v1/allocations/          list (filter ?is_temporary= , ?resident=)   manage_allocations
GET      /api/v1/allocations/{id}/     retrieve                                     manage_allocations
GET      /api/v1/transfers/            transfer history (filter ?resident= , ?is_temporary=)  manage_allocations
GET      /api/v1/transfers/{id}/       retrieve                                     manage_allocations
POST     /api/v1/transfers/            perform a transfer (moves the Allocation)    manage_allocations
```
Allocations are read-only over the API — they change only via check-in
(Module 05) and transfers. Transfers are create + read only (append-only
history, no update/delete).

## Business rules (each maps to a test)
1. Check-in (Module 05 admission) auto-creates the resident's Allocation
   mirroring the admitted bed: `allocated_bed` = admitted bed, contracted
   terms copied from the Admission, `is_temporary=false`. (Module 05's
   `perform_create` now calls `services.create_initial_allocation` inside
   its transaction.)
2. A **permanent** transfer (`is_temporary=false`) moves the resident to a
   new bed and updates the Allocation's contracted terms: `contracted_rent`
   becomes the supplied `new_rent`, or — if omitted — the new bed's rack
   rate for the resident's contracted food preference; `contracted_sharing_type`/
   `contracted_room_category` update to the new room; the temporary flag is
   cleared. This is also how a temporarily-placed resident is moved back to
   a proper room.
3. A **temporary** transfer (`is_temporary=true`) moves the resident's bed
   but leaves the whole contracted deal untouched (invariant 3): `new_rent`
   is forced equal to the current `contracted_rent`, `is_temporary=true`,
   `temporary_since` = transfer date, `expected_move_date`/`temporary_note`
   captured.
4. `rent_effective_date` follows the property's Module 2B setting:
   **Immediately** → the transfer date; **Next Billing Cycle** (default) →
   the 1st of the following month. (Temporary transfers set it to the
   transfer date since no rent change is scheduled.)
5. Every transfer swaps bed statuses — previous bed → Available, new bed →
   Occupied — which cascades to the Module 02 room-status sync. The whole
   operation is atomic (`@transaction.atomic` in `services.perform_transfer`).
6. A transfer is rejected if: the resident has no allocation
   (`resident_not_allocated`), the resident isn't Active/Notice-Period
   (`resident_not_transferable`), the new bed is in a different property
   (`bed_property_mismatch`), the new bed is the current bed (`same_bed`),
   or the new bed isn't Available (`bed_not_available`).
7. Allocation and Transfer are gated by `manage_allocations` (excludes
   Receptionist and Resident) and scoped to the actor's visible properties
   (reuses `apps.properties.services.visible_property_ids` /
   `can_view_property`).
8. Every transfer writes a `resident.transferred` audit log with before/
   after bed, rent, temporary flag, and effective date.
9. `allocations` and `transfers` are RLS-enforced; isolation proven the
   same way as the other Module 04/05 tables.

## Permissions
- `manage_allocations` (Super Admin, Owner, Manager): all allocation/transfer
  endpoints, scoped to assigned properties for Manager.
- Receptionist and Resident: no access.

## Edge cases handled
- The temporary-allocation dashboard is `GET /allocations/?is_temporary=true`.
- `actual_*` vs `contracted_*` on a temporary allocation surface the PRD
  badge data ("Currently in 2-sharing / Contracted for 4-sharing @ ₹7,000").
- A permanent transfer to any room clears an existing temporary placement
  (no separate "resolve temporary" endpoint needed).
- Same DB-level protection as elsewhere: a cross-tenant allocation INSERT
  is rejected by RLS even with a valid same-tenant resident/bed.

## Open questions / Decisions
- [DECISION 2026-07-03] **Temporary allocation arises only via transfers**
  (confirmed with the product owner). Module 05 snapshots contracted terms
  FROM the admitted bed, so an allocation is never temporary at check-in;
  the PRD's "preferred type unavailable at admission" case is modelled as a
  subsequent temporary transfer rather than reworking Module 05 to let
  contracted terms differ from the physical bed at check-in.
- [DECISION 2026-07-03] **Permanent-transfer new rent defaults from the new
  bed, overridable** (confirmed with the product owner). `new_rent`
  pre-fills from the destination bed's rack rate for the resident's food
  preference but can be overridden; once set it's snapshotted onto the
  allocation and never auto-recomputed (invariant 2).
- [DECISION 2026-07-03] `Allocation`/`Transfer` live in `apps.residents`
  alongside `Resident`/`Admission` (same rationale as Module 05: the
  bootstrap scaffolded domain-grouped apps, not one per PRD module, and
  these are resident-lifecycle records).
- [DECISION 2026-07-03] Allocation is created at check-in and is a strict
  1:1 with the resident (like Admission). Re-admission after vacating is a
  new Resident record (Module 05 decision), so there's never a second
  allocation for the same resident.
- [DECISION 2026-07-03] `actual_sharing_type`/`actual_room_category` are
  derived (serializer read-only properties), not stored, so they can't
  drift from the physical room — consistent with the Module 02 decision on
  auto-calculated counts.
- [DECISION 2026-07-03] Transfers are allowed for Active **and Notice
  Period** residents (both are physically present). Vacated/Absconded/
  Blacklisted residents cannot be transferred.
- [DECISION 2026-07-03] A transfer must stay within the resident's own
  property (`bed_property_mismatch` otherwise). Cross-property moves aren't
  in the PRD and would muddy property-scoped occupancy; treat as a
  vacate-and-readmit if ever needed.
- [OPEN] The `rent_effective_date` is recorded but nothing consumes it yet
  — Module 08 (Billing) is what will actually split/apply rent on the
  effective date. Likewise the temporary-allocation "suggest matching room"
  automation is explicitly V2 (PRD) and not built.

## Changelog
- 2026-06-xx  Created stub.
- 2026-07-03  Built: `Allocation` + `Transfer` models (RLS, in
  apps.residents), check-in allocation hook into Module 05, permanent/
  temporary transfer service with property-driven rent-effective-date,
  read-only allocation API + transfer create/history API, audit logging,
  23 tests. Spec written to as-built.
