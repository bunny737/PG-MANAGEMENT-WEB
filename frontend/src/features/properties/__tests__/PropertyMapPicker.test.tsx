/* eslint-disable i18next/no-literal-string -- test fixtures, not UI copy */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import properties from "@/messages/en/properties.json";
import { PropertyMapPicker } from "../PropertyMapPicker";

type Listener = (event?: unknown) => void;

// A stand-in for the Google Maps libraries, recording what the picker does with them.
function installFakeGoogle() {
  const maps: FakeMap[] = [];
  const markers: FakeMarker[] = [];
  const searchBoxes: HTMLElement[] = [];
  const geocode = vi.fn();

  class FakeMap {
    listeners: Record<string, Listener> = {};
    panTo = vi.fn();
    setZoom = vi.fn();
    getZoom = vi.fn(() => 10);
    constructor(
      public el: HTMLElement,
      public options: Record<string, unknown>
    ) {
      maps.push(this);
    }
    addListener(event: string, handler: Listener) {
      this.listeners[event] = handler;
    }
  }

  class FakeMarker {
    listeners: Record<string, Listener> = {};
    position: unknown;
    map: unknown;
    gmpDraggable = false;
    title = "";
    constructor(options: Record<string, unknown>) {
      Object.assign(this, options);
      markers.push(this);
    }
    addListener(event: string, handler: Listener) {
      this.listeners[event] = handler;
    }
  }

  function FakeSearchBox() {
    const el = document.createElement("div");
    searchBoxes.push(el);
    return el;
  }

  class FakeGeocoder {
    geocode = geocode;
  }

  const libraries: Record<string, unknown> = {
    maps: { Map: FakeMap },
    marker: { AdvancedMarkerElement: FakeMarker },
    places: { PlaceAutocompleteElement: FakeSearchBox },
    geocoding: { Geocoder: FakeGeocoder },
  };
  const importLibrary = vi.fn(async (name: string) => libraries[name]);
  window.google = { maps: { importLibrary } };
  return { maps, markers, searchBoxes, geocode, importLibrary };
}

const noop = () => {};

function renderPicker(props: Partial<React.ComponentProps<typeof PropertyMapPicker>> = {}) {
  const onChange = vi.fn();
  const onAddressSelect = vi.fn();
  const element = (next: Partial<React.ComponentProps<typeof PropertyMapPicker>>) => (
    <NextIntlClientProvider locale="en" messages={{ properties }}>
      <PropertyMapPicker
        latitude={null}
        longitude={null}
        onChange={onChange}
        onAddressSelect={onAddressSelect}
        {...props}
        {...next}
      />
    </NextIntlClientProvider>
  );
  const view = render(element({}));
  return { onChange, onAddressSelect, rerender: (next: Partial<React.ComponentProps<typeof PropertyMapPicker>>) => view.rerender(element(next)) };
}

const settle = () => act(async () => {});

describe("PropertyMapPicker", () => {
  beforeEach(() => {
    delete window.google;
    localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  describe("without a Google Maps key", () => {
    beforeEach(() => {
      vi.stubEnv("NEXT_PUBLIC_GOOGLE_MAPS_API_KEY", "");
    });

    test("says maps are unavailable, offers no way to type a key, and keeps manual coordinates working", async () => {
      const { onChange } = renderPicker();
      await settle();

      expect(screen.getByText(properties.form.mapApiKeyMissing)).toBeTruthy();
      expect(screen.queryByPlaceholderText(/api key/i)).toBeNull();
      expect((screen.getByPlaceholderText(properties.form.searchLocationPlaceholder) as HTMLInputElement).disabled).toBe(true);

      fireEvent.change(screen.getByLabelText(/Latitude/), { target: { value: "17.385044" } });
      fireEvent.change(screen.getByLabelText(/Longitude/), { target: { value: "78.486671" } });
      expect(onChange).toHaveBeenLastCalledWith({ latitude: 17.385044, longitude: 78.486671 });
    });

    test("never reads a key from browser storage", async () => {
      localStorage.setItem("GMAPS_API_KEY", "stored-key");
      renderPicker();
      await settle();
      expect(document.head.querySelector("script#google-maps-script-loader")).toBeNull();
      expect(screen.getByText(properties.form.mapApiKeyMissing)).toBeTruthy();
    });

    test("a pinned location still links out to Google Maps", async () => {
      renderPicker({ latitude: 17.4, longitude: 78.5 });
      await settle();
      expect(screen.getByRole("link", { name: new RegExp(properties.form.viewOnGoogleMaps) }).getAttribute("href")).toContain(
        "query=17.4,78.5"
      );
    });

    test("rejects out-of-range or half-typed coordinates", async () => {
      const { onChange } = renderPicker();
      fireEvent.change(screen.getByLabelText(/Latitude/), { target: { value: "95" } });
      fireEvent.change(screen.getByLabelText(/Longitude/), { target: { value: "78" } });
      expect(onChange).not.toHaveBeenCalled();
    });
  });

  describe("with a key and Google available", () => {
    beforeEach(() => {
      vi.stubEnv("NEXT_PUBLIC_GOOGLE_MAPS_API_KEY", "test-key");
      vi.stubEnv("NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID", "map-123");
    });

    test("builds the map with a Map ID, mounts the new search element, and shows the drag hint", async () => {
      const google = installFakeGoogle();
      renderPicker();
      await settle();

      expect(google.maps).toHaveLength(1);
      expect(google.maps[0].options.mapId).toBe("map-123");
      expect(google.searchBoxes[0].isConnected).toBe(true);
      expect(screen.getByText(properties.form.dragPinHint)).toBeTruthy();
      expect(screen.queryByPlaceholderText(properties.form.searchLocationPlaceholder)).toBeNull(); // stand-in input is gone
      const libraries = google.importLibrary.mock.calls.map(([name]) => name).sort();
      expect(libraries).toEqual(["geocoding", "maps", "marker", "places"]);
    });

    test("an existing pin gets a draggable advanced marker", async () => {
      const google = installFakeGoogle();
      renderPicker({ latitude: 17.4, longitude: 78.5 });
      await settle();

      expect(google.markers).toHaveLength(1);
      expect(google.markers[0]).toMatchObject({
        position: { lat: 17.4, lng: 78.5 },
        gmpDraggable: true,
        title: properties.form.markerTitle,
      });
      expect(google.maps[0].panTo).toHaveBeenCalledWith({ lat: 17.4, lng: 78.5 });
    });

    test("a disabled picker gets a non-draggable marker and ignores map clicks", async () => {
      const google = installFakeGoogle();
      const { onChange } = renderPicker({ latitude: 17.4, longitude: 78.5, disabled: true });
      await settle();
      expect(google.markers[0].gmpDraggable).toBe(false);
      google.maps[0].listeners.click({ latLng: { lat: () => 1, lng: () => 2 } });
      expect(onChange).not.toHaveBeenCalled();
    });

    test("clicking the map sets the pin (rounded) and fills the address from the geocoder", async () => {
      const google = installFakeGoogle();
      google.geocode.mockResolvedValue({
        results: [
          { types: ["route"], formatted_address: "Road, Hyderabad", address_components: [] },
          {
            types: ["street_address"],
            formatted_address: "Plot 1, Madhapur",
            address_components: [
              { long_name: "Madhapur", types: ["sublocality_level_1"] },
              { long_name: "Hyderabad", types: ["locality"] },
              { long_name: "Telangana", types: ["administrative_area_level_1"] },
              { long_name: "500081", types: ["postal_code"] },
            ],
          },
        ],
      });
      const { onChange, onAddressSelect } = renderPicker();
      await settle();

      await act(async () => {
        google.maps[0].listeners.click({ latLng: { lat: () => 17.3850441234, lng: () => 78.4866719876 } });
      });
      expect(onChange).toHaveBeenCalledWith({ latitude: 17.385044, longitude: 78.486672 });
      expect(google.geocode).toHaveBeenCalledWith({ location: { lat: 17.385044, lng: 78.486672 } });
      expect(onAddressSelect).toHaveBeenCalledWith({
        address: "Madhapur",
        city: "Hyderabad",
        state: "Telangana",
        pincode: "500081",
      });
    });

    test("a failing geocoder leaves the pin set and doesn't throw", async () => {
      const google = installFakeGoogle();
      google.geocode.mockRejectedValue(new Error("OVER_QUERY_LIMIT"));
      const { onChange, onAddressSelect } = renderPicker();
      await settle();
      await act(async () => {
        google.maps[0].listeners.click({ latLng: { lat: () => 1, lng: () => 2 } });
      });
      expect(onChange).toHaveBeenCalledWith({ latitude: 1, longitude: 2 });
      expect(onAddressSelect).not.toHaveBeenCalled();
    });

    test("picking a search result (Places API New) moves the map and fills the address", async () => {
      const google = installFakeGoogle();
      const place = {
        location: { lat: () => 17.44, lng: () => 78.38 },
        formattedAddress: "Hitech City, Hyderabad",
        addressComponents: [
          { longText: "Hitech City", types: ["sublocality_level_1"] },
          { longText: "Hyderabad", types: ["locality"] },
          { longText: "Telangana", types: ["administrative_area_level_1"] },
          { longText: "500081", types: ["postal_code"] },
        ],
        fetchFields: vi.fn(async () => ({})),
      };
      const { onChange, onAddressSelect } = renderPicker();
      await settle();

      await act(async () => {
        google.searchBoxes[0].dispatchEvent(
          Object.assign(new Event("gmp-select"), { placePrediction: { toPlace: () => place } })
        );
      });
      expect(place.fetchFields).toHaveBeenCalledWith({
        fields: ["location", "formattedAddress", "addressComponents"],
      });
      expect(onChange).toHaveBeenCalledWith({ latitude: 17.44, longitude: 78.38 });
      expect(google.maps[0].panTo).toHaveBeenCalledWith({ lat: 17.44, lng: 78.38 });
      expect(onAddressSelect).toHaveBeenCalledWith({
        address: "Hitech City",
        city: "Hyderabad",
        state: "Telangana",
        pincode: "500081",
      });
    });

    test("the older gmp-placeselect event is handled too", async () => {
      const google = installFakeGoogle();
      const place = {
        location: { lat: () => 12.9, lng: () => 77.6 },
        formattedAddress: "Bengaluru",
        addressComponents: null,
        fetchFields: vi.fn(async () => ({})),
      };
      google.geocode.mockResolvedValue({ results: [] });
      const { onChange } = renderPicker();
      await settle();
      await act(async () => {
        google.searchBoxes[0].dispatchEvent(Object.assign(new Event("gmp-placeselect"), { place }));
      });
      expect(onChange).toHaveBeenCalledWith({ latitude: 12.9, longitude: 77.6 });
      expect(google.geocode).toHaveBeenCalled(); // no components: fall back to reverse geocoding
    });

    test("dragging the marker reports the new position", async () => {
      const google = installFakeGoogle();
      google.geocode.mockResolvedValue({ results: [] });
      const { onChange } = renderPicker({ latitude: 17.4, longitude: 78.5 });
      await settle();

      google.markers[0].position = { lat: () => 17.4123456789, lng: () => 78.5 };
      await act(async () => {
        google.markers[0].listeners.dragend();
      });
      expect(onChange).toHaveBeenCalledWith({ latitude: 17.412346, longitude: 78.5 });
    });

    test("moving the pin from outside moves the marker; clearing it removes the marker", async () => {
      const google = installFakeGoogle();
      const { rerender } = renderPicker({ latitude: 17.4, longitude: 78.5 });
      await settle();

      rerender({ latitude: 18, longitude: 79 });
      await settle();
      expect(google.markers).toHaveLength(1); // moved, not recreated
      expect(google.markers[0].position).toEqual({ lat: 18, lng: 79 });

      rerender({ latitude: null, longitude: null });
      await settle();
      expect(google.markers[0].map).toBeNull();

      rerender({ latitude: 19, longitude: 80 });
      await settle();
      expect(google.markers[0].map).toBe(google.maps[0]);
    });

    test("typed coordinates follow the pin when it moves from the map", async () => {
      const google = installFakeGoogle();
      const { rerender } = renderPicker({ latitude: 17.4, longitude: 78.5 });
      await settle();
      expect((screen.getByLabelText(/Latitude/) as HTMLInputElement).value).toBe("17.4");
      rerender({ latitude: 20.1, longitude: 70.2 });
      await settle();
      expect((screen.getByLabelText(/Latitude/) as HTMLInputElement).value).toBe("20.1");
      expect(google.markers).toHaveLength(1);
    });

    test("if Google's libraries fail to load, it says so and the manual fields still work", async () => {
      const google = installFakeGoogle();
      google.importLibrary.mockRejectedValue(new Error("blocked"));
      const { onChange } = renderPicker();
      await settle();

      expect(screen.getByRole("alert").textContent).toBe(properties.form.mapLoadFailed);
      fireEvent.change(screen.getByLabelText(/Latitude/), { target: { value: "10" } });
      fireEvent.change(screen.getByLabelText(/Longitude/), { target: { value: "20" } });
      expect(onChange).toHaveBeenLastCalledWith({ latitude: 10, longitude: 20 });
    });
  });

  describe("use my location", () => {
    beforeEach(() => {
      vi.stubEnv("NEXT_PUBLIC_GOOGLE_MAPS_API_KEY", "");
    });

    test("an unsupported browser gets an inline message, not an alert()", async () => {
      const alertSpy = vi.spyOn(window, "alert").mockImplementation(noop);
      Object.defineProperty(navigator, "geolocation", { value: undefined, configurable: true });
      renderPicker();
      fireEvent.click(screen.getByRole("button", { name: new RegExp(properties.form.locateMeButton) }));
      expect(screen.getByRole("alert").textContent).toBe(properties.form.locateUnsupported);
      expect(alertSpy).not.toHaveBeenCalled();
    });

    test("a denied permission shows the reason inline", async () => {
      const getCurrentPosition = vi.fn((_ok: unknown, fail: (e: { message: string }) => void) =>
        fail({ message: "User denied" })
      );
      Object.defineProperty(navigator, "geolocation", { value: { getCurrentPosition }, configurable: true });
      renderPicker();
      fireEvent.click(screen.getByRole("button", { name: new RegExp(properties.form.locateMeButton) }));
      expect(screen.getByRole("alert").textContent).toBe("Could not get your location: User denied");
    });

    test("a successful fix sets the pin", async () => {
      const getCurrentPosition = vi.fn((ok: (p: { coords: { latitude: number; longitude: number } }) => void) =>
        ok({ coords: { latitude: 17.4123456789, longitude: 78.5 } })
      );
      Object.defineProperty(navigator, "geolocation", { value: { getCurrentPosition }, configurable: true });
      const { onChange } = renderPicker();
      fireEvent.click(screen.getByRole("button", { name: new RegExp(properties.form.locateMeButton) }));
      expect(onChange).toHaveBeenCalledWith({ latitude: 17.412346, longitude: 78.5 });
    });
  });
});
