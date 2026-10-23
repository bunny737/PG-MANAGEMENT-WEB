/* eslint-disable i18next/no-literal-string -- test fixtures, not UI copy */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import commonEn from "@/messages/en/common.json";
import residentsEn from "@/messages/en/residents.json";
import { ApiError, createTransfer, getPropertyLayout, type PropertyLayout, type Resident } from "@/lib/api";
import { TransferRoomDialog } from "../TransferRoomDialog";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, getPropertyLayout: vi.fn(), createTransfer: vi.fn() };
});

const counts = { total: 0, occupied: 0, reserved: 0, maintenance: 0, available: 0, occupancy_rate: null };

function bed(id: string, number: string, availability: "available" | "occupied") {
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
  };
}

const LAYOUT: PropertyLayout = {
  property: { id: "p1", name: "Greenwood Girls Hostel" },
  period: "2026-10",
  as_of: "2026-10-20",
  due_soon_days: 5,
  counts,
  finance: null,
  redacted: [],
  buildings: [
    {
      id: "b1",
      name: "Block A",
      order: 1,
      counts,
      floors: [
        {
          id: "f1",
          name: "Ground Floor",
          order: 1,
          counts,
          rooms: [
            {
              id: "r1", room_number: "G01", sharing_type: 2, category: "ac", status: "available", counts,
              rack_rate_with_food: "12000.00", rack_rate_without_food: "10000.00",
              beds: [bed("bed-a", "G01-A", "occupied"), bed("bed-b", "G01-B", "available")],
            },
            {
              id: "r2", room_number: "G02", sharing_type: 3, category: "non_ac", status: "occupied", counts,
              rack_rate_with_food: "9000.00", rack_rate_without_food: "8000.00",
              beds: [bed("bed-c", "G02-A", "occupied")],
            },
          ],
        },
      ],
    },
  ],
};

const RESIDENT = {
  id: "res-1",
  property: "p1",
  status: "active",
  contracted_rent: "7500.00",
  food_preference: "with_food",
} as Resident;

function renderDialog(overrides: Partial<Resident> = {}) {
  const onClose = vi.fn();
  const onTransferred = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale="en" messages={{ residents: residentsEn, common: commonEn }} onError={() => {}}>
        <TransferRoomDialog resident={{ ...RESIDENT, ...overrides }} onClose={onClose} onTransferred={onTransferred} />
      </NextIntlClientProvider>
    </QueryClientProvider>
  );
  return { onClose, onTransferred };
}

describe("TransferRoomDialog", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(getPropertyLayout).mockResolvedValue(LAYOUT);
  });

  it("lists only rooms that have a vacant bed, and only the vacant beds", async () => {
    renderDialog();
    const room = (await screen.findByLabelText(/Destination room/)) as HTMLSelectElement;

    const labels = Array.from(room.options).map((o) => o.textContent);
    expect(labels.some((l) => l?.includes("G01"))).toBe(true);
    expect(labels.some((l) => l?.includes("G02"))).toBe(false);

    fireEvent.change(room, { target: { value: "r1" } });
    const bedSelect = screen.getByLabelText(/Destination bed/) as HTMLSelectElement;
    const beds = Array.from(bedSelect.options).map((o) => o.textContent);
    expect(beds).toContain("Bed G01-B");
    expect(beds).not.toContain("Bed G01-A");
  });

  it("shows the current rent, the rack rate for the resident's food preference, and keeps the property fixed", async () => {
    renderDialog();
    await screen.findByLabelText(/Destination room/);

    expect(screen.getByText("Current rent: ₹7,500.00/mo")).toBeTruthy();
    expect(screen.getByText("Greenwood Girls Hostel")).toBeTruthy();

    fireEvent.change(screen.getByLabelText(/Destination room/), { target: { value: "r1" } });
    fireEvent.change(screen.getByLabelText(/Destination bed/), { target: { value: "bed-b" } });
    expect(screen.getByText("Rack rate: ₹12,000.00/mo (with food)")).toBeTruthy();
  });

  it("hides the current rent when the API omitted it (no view_finance)", async () => {
    renderDialog({ contracted_rent: undefined });
    await screen.findByLabelText(/Destination room/);
    expect(screen.queryByText(/Current rent/)).toBeNull();
  });

  it("keeps Confirm disabled until a bed is chosen, then posts a permanent transfer without a rent override", async () => {
    vi.mocked(createTransfer).mockResolvedValue({} as never);
    const { onClose, onTransferred } = renderDialog();
    const confirm = (await screen.findByRole("button", { name: "Confirm Transfer" })) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);

    fireEvent.change(screen.getByLabelText(/Destination room/), { target: { value: "r1" } });
    fireEvent.change(screen.getByLabelText(/Destination bed/), { target: { value: "bed-b" } });
    fireEvent.change(screen.getByLabelText("Transfer date"), { target: { value: "2026-10-20" } });
    expect(confirm.disabled).toBe(false);
    fireEvent.click(confirm);

    await waitFor(() => expect(onTransferred).toHaveBeenCalled());
    expect(createTransfer).toHaveBeenCalledWith({
      resident: "res-1",
      new_bed: "bed-b",
      transfer_date: "2026-10-20",
      is_temporary: false,
      reason: undefined,
      expected_move_date: undefined,
      temporary_note: undefined,
    });
    expect(onClose).toHaveBeenCalled();
  });

  it("sends the temporary flag, expected move-back date and note for a temporary move", async () => {
    vi.mocked(createTransfer).mockResolvedValue({} as never);
    renderDialog();
    await screen.findByLabelText(/Destination room/);

    fireEvent.change(screen.getByLabelText(/Destination room/), { target: { value: "r1" } });
    fireEvent.change(screen.getByLabelText(/Destination bed/), { target: { value: "bed-b" } });
    fireEvent.change(screen.getByLabelText("Transfer date"), { target: { value: "2026-10-20" } });
    fireEvent.click(screen.getByLabelText(/Temporary move/));
    fireEvent.change(screen.getByLabelText("Expected move-back date"), { target: { value: "2026-11-01" } });
    fireEvent.change(screen.getByLabelText("Note"), { target: { value: "AC repair" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm Transfer" }));

    await waitFor(() => expect(createTransfer).toHaveBeenCalled());
    expect(vi.mocked(createTransfer).mock.calls[0][0]).toMatchObject({
      is_temporary: true,
      expected_move_date: "2026-11-01",
      temporary_note: "AC repair",
    });
  });

  it("shows the server's message and stays open when the transfer is rejected", async () => {
    vi.mocked(createTransfer).mockRejectedValue(new ApiError(400, { new_bed: ["This bed is not available."] }));
    const { onClose, onTransferred } = renderDialog();
    await screen.findByLabelText(/Destination room/);

    fireEvent.change(screen.getByLabelText(/Destination room/), { target: { value: "r1" } });
    fireEvent.change(screen.getByLabelText(/Destination bed/), { target: { value: "bed-b" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm Transfer" }));

    expect(await screen.findByText("This bed is not available.")).toBeTruthy();
    expect(onTransferred).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("explains when the property has no vacant beds", async () => {
    vi.mocked(getPropertyLayout).mockResolvedValue({
      ...LAYOUT,
      buildings: [{ ...LAYOUT.buildings[0], floors: [{ ...LAYOUT.buildings[0].floors[0], rooms: [LAYOUT.buildings[0].floors[0].rooms[1]] }] }],
    });
    renderDialog();
    expect(await screen.findByText("No vacant beds are available in this property.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Confirm Transfer" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
