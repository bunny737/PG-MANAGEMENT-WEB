import type { PropertyLayout } from "./api";
import { compareMoney } from "./money";

/**
 * Turns a property's bed layout (GET /properties/{id}/layout/) into the Vacancies screen's shape:
 * the rooms that have a vacant bed or a resident on notice. Pure, so the rules are testable.
 */

export interface VacantBed {
  id: string;
  number: string;
}

export interface NoticeResident {
  residentId: string;
  name: string;
  bedNumber: string;
  noticeDate: string | null;
  vacatingDate: string | null;
}

export interface VacancyRoom {
  id: string;
  roomNumber: string;
  /** Only set when the property has more than one building: floor and room names repeat across buildings. */
  buildingName: string | null;
  floorName: string;
  sharingType: number;
  rate: { amount: string; isFrom: boolean };
  vacantBeds: VacantBed[];
  onNotice: NoticeResident[];
}

export interface PropertyVacancies {
  rooms: VacancyRoom[];
  vacantCount: number;
  /** Null when it is unknowable: without view_resident_profile the layout hides every resident. */
  onNoticeCount: number | null;
}

/** The room's display rate: the lower of its with-food and without-food rack rates (`isFrom` when they
 * differ). Compared as money, never as strings. Falls back to the with-food rate when either is unparseable. */
export function roomRate(withFood: string, withoutFood: string): { amount: string; isFrom: boolean } {
  const cmp = compareMoney(withFood, withoutFood);
  if (cmp === null) return { amount: withFood, isFrom: false };
  if (cmp === 0) return { amount: withFood, isFrom: false };
  return { amount: cmp < 0 ? withFood : withoutFood, isFrom: true };
}

export function buildPropertyVacancies(layout: PropertyLayout): PropertyVacancies {
  const residentsVisible = !layout.redacted.includes("resident");
  const multipleBuildings = layout.buildings.length > 1;
  const rooms: VacancyRoom[] = [];

  for (const building of layout.buildings) {
    for (const floor of building.floors) {
      for (const room of floor.rooms) {
        const vacantBeds = room.beds
          .filter((bed) => bed.availability === "available")
          .map((bed) => ({ id: bed.id, number: bed.bed_number }));
        const onNotice = residentsVisible
          ? room.beds.flatMap((bed) =>
              bed.resident?.on_notice
                ? [
                    {
                      residentId: bed.resident.id,
                      name: bed.resident.name,
                      bedNumber: bed.bed_number,
                      noticeDate: bed.resident.notice_date,
                      vacatingDate: bed.resident.expected_vacate_date,
                    },
                  ]
                : []
            )
          : [];
        if (vacantBeds.length === 0 && onNotice.length === 0) continue;
        rooms.push({
          id: room.id,
          roomNumber: room.room_number,
          buildingName: multipleBuildings ? building.name : null,
          floorName: floor.name,
          sharingType: room.sharing_type,
          rate: roomRate(room.rack_rate_with_food, room.rack_rate_without_food),
          vacantBeds,
          onNotice,
        });
      }
    }
  }

  return {
    rooms,
    vacantCount: rooms.reduce((sum, room) => sum + room.vacantBeds.length, 0),
    onNoticeCount: residentsVisible ? rooms.reduce((sum, room) => sum + room.onNotice.length, 0) : null,
  };
}
