import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AddRoomForm } from "../AddRoomForm";
import { ApiError, createRoom, getFloor, listFloors } from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, getFloor: vi.fn(), listFloors: vi.fn(), createRoom: vi.fn() };
});
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));
vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
}));

const FLOOR_ID = "11111111-1111-4111-8111-111111111111";
const PROPERTY_ID = "22222222-2222-4222-8222-222222222222";

function fillAndSubmit(container: HTMLElement) {
  const field = (id: string) => container.querySelector<HTMLInputElement>(`#${id}`)!;
  fireEvent.change(field("room_number"), { target: { value: "101" } });
  fireEvent.change(field("rent_with_food"), { target: { value: "5000" } });
  fireEvent.change(field("rent_without_food"), { target: { value: "4000" } });
  fireEvent.click(screen.getByRole("button", { name: "createButton" }));
}

async function renderLoaded() {
  const view = render(<AddRoomForm propertyId={PROPERTY_ID} floorId={FLOOR_ID} />);
  await waitFor(() => expect(view.container.querySelector("#room_number")).not.toBeNull());
  return view;
}

describe("AddRoomForm", () => {
  beforeEach(() => {
    vi.mocked(getFloor).mockResolvedValue({ id: FLOOR_ID, building: "b1" } as Awaited<ReturnType<typeof getFloor>>);
    vi.mocked(listFloors).mockResolvedValue([{ id: FLOOR_ID, name: "Ground" }] as Awaited<ReturnType<typeof listFloors>>);
    vi.mocked(createRoom).mockReset();
  });

  it("creates the room and its beds in one request and lists the beds the server returned", async () => {
    vi.mocked(createRoom).mockResolvedValue({
      id: "r1",
      room_number: "101",
      rack_rate_with_food: "5000.00",
      rack_rate_without_food: "4000.00",
      beds: [{ bed_number: "101-A" }, { bed_number: "101-B" }],
    } as Awaited<ReturnType<typeof createRoom>>);

    const { container } = await renderLoaded();
    fillAndSubmit(container);

    expect(await screen.findByText("101-A")).toBeTruthy();
    expect(screen.getByText("101-B")).toBeTruthy();
    expect(createRoom).toHaveBeenCalledTimes(1);
    expect(createRoom).toHaveBeenCalledWith(
      expect.objectContaining({ floor: FLOOR_ID, room_number: "101", sharing_type: 2, auto_create_beds: true }),
    );
  });

  it("shows the server's message and no success modal when the plan bed limit is reached", async () => {
    const message = "Your plan allows a maximum of 500 beds. Upgrade to add more.";
    vi.mocked(createRoom).mockRejectedValue(new ApiError(400, { detail: message, code: "BED_LIMIT_REACHED" }));
    vi.spyOn(console, "error").mockImplementation(() => {});

    const { container } = await renderLoaded();
    fillAndSubmit(container);

    expect(await screen.findByText(message)).toBeTruthy();
    expect(screen.queryByText("modalTitle")).toBeNull();
    expect(createRoom).toHaveBeenCalledTimes(1);
  });
});
