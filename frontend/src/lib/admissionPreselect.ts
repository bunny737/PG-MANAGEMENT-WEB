import type { PropertyLayout } from "./api";

/** Where a bed sits in its property, so the admission wizard can select the whole chain (building, floor, room, bed). */
export interface BedChain {
  buildingId: string;
  floorId: string;
  roomId: string;
  bedId: string;
}

/** The chain for `bedId` within a property layout, or null when that bed isn't there or isn't free to admit into
 * (a stale link from the Vacancies screen must fall back to the normal empty wizard, never select a taken bed). */
export function findBedChain(layout: PropertyLayout, bedId: string): BedChain | null {
  for (const building of layout.buildings) {
    for (const floor of building.floors) {
      for (const room of floor.rooms) {
        const bed = room.beds.find((candidate) => candidate.id === bedId);
        if (bed) {
          return bed.availability === "available"
            ? { buildingId: building.id, floorId: floor.id, roomId: room.id, bedId: bed.id }
            : null;
        }
      }
    }
  }
  return null;
}
