import { describe, expect, test } from "vitest";
import { parseAddressComponents } from "../mapAddress";

describe("parseAddressComponents", () => {
  test("reads the Geocoder's shape (long_name)", () => {
    expect(
      parseAddressComponents(
        [
          { long_name: "Plot 12", types: ["premise"] },
          { long_name: "Road No. 3", types: ["route"] },
          { long_name: "Banjara Hills", types: ["sublocality_level_1", "sublocality"] },
          { long_name: "Hyderabad", types: ["locality"] },
          { long_name: "Telangana", types: ["administrative_area_level_1"] },
          { long_name: "500 034", types: ["postal_code"] },
        ],
        "formatted"
      )
    ).toEqual({
      address: "Plot 12, Road No. 3, Banjara Hills",
      city: "Hyderabad",
      state: "Telangana",
      pincode: "500034",
    });
  });

  test("reads the Places API (New) shape (longText)", () => {
    expect(
      parseAddressComponents([
        { longText: "Madhapur", types: ["sublocality_level_1"] },
        { longText: "Hyderabad", types: ["locality"] },
        { longText: "Telangana", types: ["administrative_area_level_1"] },
        { longText: "500081", types: ["postal_code"] },
      ])
    ).toEqual({ address: "Madhapur", city: "Hyderabad", state: "Telangana", pincode: "500081" });
  });

  test("falls back to the formatted address, and to a level-2 area for the city", () => {
    expect(
      parseAddressComponents([{ long_name: "Medchal", types: ["administrative_area_level_2"] }], "Somewhere, India")
    ).toEqual({ address: "Somewhere, India", city: "Medchal", state: "", pincode: "" });
  });

  test("ignores components without a name and copes with no input", () => {
    expect(parseAddressComponents([{ types: ["locality"] }])).toEqual({
      address: "",
      city: "",
      state: "",
      pincode: "",
    });
    expect(parseAddressComponents()).toEqual({ address: "", city: "", state: "", pincode: "" });
  });
});
