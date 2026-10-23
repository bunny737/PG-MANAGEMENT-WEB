import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import {
  ApiError,
  createTenantFeature,
  getProperty,
  listBeds,
  listBuildings,
  listComplaints,
  listFeatureCatalog,
  listFloors,
  listPropertyFeatures,
  listRooms,
  listResidents,
  listTenantFeatures,
  replacePropertyFeatures,
  updateProperty,
} from "../api";

// A failed request must surface as an error. Nothing here may answer with invented records, a
// built-in catalog, or a silent empty list: the user would be looking at data that isn't theirs.
describe("api: no mock or fabricated data on failure", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn(async () => new Response(JSON.stringify({ detail: "boom" }), { status: 500 }));
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("the feature catalog, tenant features and custom-feature creation reject on a server error", async () => {
    await expect(listFeatureCatalog()).rejects.toBeInstanceOf(ApiError);
    await expect(listTenantFeatures()).rejects.toBeInstanceOf(ApiError);
    await expect(createTenantFeature("Gym")).rejects.toBeInstanceOf(ApiError);
  });

  test("a network failure rejects too, rather than inventing a custom feature", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(createTenantFeature("Gym")).rejects.toMatchObject({ status: 0 });
    await expect(listFeatureCatalog()).rejects.toMatchObject({ status: 0 });
  });

  test.each([
    ["getProperty", () => getProperty("skyline")],
    ["updateProperty", () => updateProperty("skyline", { name: "x" })],
    ["listBuildings", () => listBuildings("skyline")],
    ["listFloors", () => listFloors("1")],
    ["listRooms", () => listRooms("1")],
    ["listBeds", () => listBeds("1")],
    ["listResidents", () => listResidents("skyline")],
    ["listComplaints", () => listComplaints({ resident: "1" })],
    ["listPropertyFeatures", () => listPropertyFeatures("sunset")],
    ["replacePropertyFeatures", () => replacePropertyFeatures("skyline", { building: null, items: [] })],
  ])("%s rejects a non-UUID id with a 404 and never calls the server", async (_name, call) => {
    await expect(call()).rejects.toMatchObject({ status: 404 });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
