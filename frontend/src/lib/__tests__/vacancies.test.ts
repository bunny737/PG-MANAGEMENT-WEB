import { describe, expect, test } from "vitest";
import type { LayoutBed, LayoutBuilding, LayoutRoom, PropertyLayout } from "../api";
import { buildPropertyVacancies, roomRate } from "../vacancies";

const COUNTS = { total: 0, occupied: 0, reserved: 0, maintenance: 0, available: 0, occupancy_rate: null };

function bed(id: string, number: string, availability: LayoutBed["availability"], extra: Partial<LayoutBed> = {}): LayoutBed {
  return {
    id,
    bed_number: number,
    availability,
    allowed_transitions: [],
    reserved_for: null,
    reserved_until: null,
    rack_rate_with_food: "12000.00",
    rack_rate_without_food: "10000.00",
    resident: null,
    payment: null,
    ...extra,
  };
}

function room(id: string, number: string, beds: LayoutBed[], rates: [string, string] = ["12000.00", "10000.00"]): LayoutRoom {
  return {
    id,
    room_number: number,
    sharing_type: 2,
    category: "non_ac",
    status: "available",
    rack_rate_with_food: rates[0],
    rack_rate_without_food: rates[1],
    counts: COUNTS,
    beds,
  };
}

function building(id: string, name: string, floorName: string, rooms: LayoutRoom[]): LayoutBuilding {
  return { id, name, order: 0, counts: COUNTS, floors: [{ id: `${id}-f`, name: floorName, order: 0, counts: COUNTS, rooms }] };
}

function layout(buildings: LayoutBuilding[], redacted: string[] = []): PropertyLayout {
  return {
    property: { id: "p1", name: "Greenwood" },
    period: "2026-10",
    as_of: "2026-10-20",
    due_soon_days: 3,
    counts: COUNTS,
    finance: null,
    buildings,
    redacted,
  };
}

const noticeResident = {
  id: "r1",
  name: "Amit Kumar",
  phone: "9876543212",
  status: "notice_period",
  on_notice: true,
  notice_date: "2026-07-28",
  expected_vacate_date: "2026-08-27",
  is_temporary: false,
};

describe("roomRate", () => {
  test("shows the lower rack rate, comparing as money (not as strings)", () => {
    // As strings "9000.00" > "10000.00"; as money 9000 < 10000.
    expect(roomRate("10000.00", "9000.00")).toEqual({ amount: "9000.00", isFrom: true });
    expect(roomRate("9000.00", "10000.00")).toEqual({ amount: "9000.00", isFrom: true });
  });

  test("equal rates are shown plainly", () => {
    expect(roomRate("7500.00", "7500.00")).toEqual({ amount: "7500.00", isFrom: false });
  });

  test("an unparseable rate falls back to the with-food rate", () => {
    expect(roomRate("12000.00", "n/a")).toEqual({ amount: "12000.00", isFrom: false });
  });
});

describe("buildPropertyVacancies", () => {
  test("keeps only rooms with a vacant bed or a resident on notice", () => {
    const result = buildPropertyVacancies(
      layout([
        building("b1", "Main", "Ground Floor", [
          room("r-full", "G01", [bed("a", "G01-A", "occupied")]),
          room("r-vacant", "G02", [bed("b", "G02-A", "available"), bed("c", "G02-B", "occupied")]),
          room("r-notice", "G03", [bed("d", "G03-A", "occupied", { resident: noticeResident })]),
        ]),
      ])
    );

    expect(result.rooms.map((r) => r.roomNumber)).toEqual(["G02", "G03"]);
    expect(result.vacantCount).toBe(1);
    expect(result.onNoticeCount).toBe(1);
    expect(result.rooms[1].onNotice[0]).toMatchObject({
      residentId: "r1",
      bedNumber: "G03-A",
      noticeDate: "2026-07-28",
      vacatingDate: "2026-08-27",
    });
  });

  test("reserved and maintenance beds are not vacant", () => {
    const result = buildPropertyVacancies(
      layout([
        building("b1", "Main", "1st", [room("r", "101", [bed("a", "101-A", "reserved"), bed("b", "101-B", "maintenance")])]),
      ])
    );
    expect(result.rooms).toEqual([]);
    expect(result.vacantCount).toBe(0);
  });

  test("without resident access the on-notice count is unknown (null), never zero, and no notice rows appear", () => {
    const result = buildPropertyVacancies(
      layout(
        [
          building("b1", "Main", "1st", [
            room("r1", "101", [bed("a", "101-A", "available"), bed("b", "101-B", "occupied", { resident: null })]),
          ]),
        ],
        ["resident"]
      )
    );

    expect(result.vacantCount).toBe(1);
    expect(result.onNoticeCount).toBeNull();
    expect(result.rooms[0].onNotice).toEqual([]);
  });

  test("a property with no residents on notice but visible residents reports a real zero", () => {
    const result = buildPropertyVacancies(
      layout([building("b1", "Main", "1st", [room("r1", "101", [bed("a", "101-A", "available")])])])
    );
    expect(result.onNoticeCount).toBe(0);
  });

  test("two buildings with the same room number stay distinct and are labelled by building", () => {
    const result = buildPropertyVacancies(
      layout([
        building("b1", "Block A", "Ground Floor", [room("room-a", "101", [bed("a", "101-A", "available")])]),
        building("b2", "Block B", "Ground Floor", [room("room-b", "101", [bed("b", "101-A", "available")])]),
      ])
    );

    expect(result.rooms.map((r) => [r.id, r.buildingName])).toEqual([
      ["room-a", "Block A"],
      ["room-b", "Block B"],
    ]);
  });

  test("a single-building property omits the building name", () => {
    const result = buildPropertyVacancies(
      layout([building("b1", "Main", "1st", [room("r1", "101", [bed("a", "101-A", "available")])])])
    );
    expect(result.rooms[0].buildingName).toBeNull();
  });

  test("the rate is the room's lower rack rate", () => {
    const result = buildPropertyVacancies(
      layout([building("b1", "Main", "1st", [room("r1", "101", [bed("a", "101-A", "available")], ["12000.00", "9000.00"])])])
    );
    expect(result.rooms[0].rate).toEqual({ amount: "9000.00", isFrom: true });
  });
});
