// Turns Google address components into the form's address fields. Accepts both shapes Google
// returns: the Geocoder's (`long_name`) and the Places API (New)'s (`longText`).

export interface PlaceAddressDetails {
  address?: string;
  city?: string;
  state?: string;
  pincode?: string;
}

export interface AddressComponent {
  types?: string[];
  long_name?: string;
  longText?: string | null;
}

const appendTo = (current: string, value: string) => (current ? `${current}, ${value}` : value);

export function parseAddressComponents(components: AddressComponent[] = [], formattedAddress = ""): PlaceAddressDetails {
  let premise = "";
  let street = "";
  let sublocality = "";
  let city = "";
  let state = "";
  let pincode = "";

  for (const component of components) {
    const types = component.types ?? [];
    const name = component.long_name ?? component.longText ?? "";
    if (!name) continue;

    if (types.includes("premise") || types.includes("subpremise")) {
      premise = name;
    } else if (types.includes("street_number") || types.includes("route")) {
      street = appendTo(street, name);
    } else if (
      types.includes("sublocality_level_1") ||
      types.includes("sublocality") ||
      types.includes("neighborhood")
    ) {
      sublocality = appendTo(sublocality, name);
    }

    if (types.includes("locality")) {
      city = name;
    } else if (!city && (types.includes("administrative_area_level_2") || types.includes("sublocality_level_2"))) {
      city = name;
    }

    if (types.includes("administrative_area_level_1")) state = name;
    if (types.includes("postal_code")) pincode = name.replace(/\D/g, "").slice(0, 6);
  }

  const detailedAddress = [premise, street, sublocality].filter(Boolean).join(", ");
  return { address: detailedAddress || formattedAddress || "", city, state, pincode };
}
