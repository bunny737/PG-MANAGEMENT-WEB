"use client";

import React, { useEffect, useRef, useState } from "react";
import {
  MapPin,
  Search,
  Navigation,
  X,
  KeyRound,
  ExternalLink,
  CheckCircle2,
  AlertCircle,
  LoaderCircle,
  Compass,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { googleMapsKey, googleMapsMapId, importMapsLibrary, loadGoogleMaps } from "@/lib/googleMaps";
import { parseAddressComponents, type AddressComponent, type PlaceAddressDetails } from "./mapAddress";

type LatLngLiteral = { lat: number; lng: number };
type LatLngLike = { lat: number | (() => number); lng: number | (() => number) };

interface GoogleMap {
  panTo(position: LatLngLiteral): void;
  setZoom(zoom: number): void;
  getZoom(): number | undefined;
  addListener(
    event: "click",
    handler: (event: { latLng?: { lat(): number; lng(): number } | null }) => void
  ): void;
}

interface GoogleMarker {
  position: LatLngLike | null | undefined;
  map: GoogleMap | null;
  gmpDraggable: boolean;
  addListener(event: "dragend", handler: () => void): void;
}

type MarkerCtor = new (options: {
  map: GoogleMap;
  position: LatLngLiteral;
  gmpDraggable: boolean;
  title: string;
}) => GoogleMarker;

interface GeocoderResult {
  types?: string[];
  formatted_address?: string;
  address_components?: AddressComponent[];
}

interface Geocoder {
  geocode(request: { location: LatLngLiteral }): Promise<{ results: GeocoderResult[] }>;
}

interface PlaceLike {
  location?: { lat(): number; lng(): number } | null;
  formattedAddress?: string | null;
  addressComponents?: AddressComponent[] | null;
  fetchFields(options: { fields: string[] }): Promise<unknown>;
}

/** `gmp-select` carries a prediction; the older `gmp-placeselect` carried the place itself. */
type PlaceSelectEvent = Event & { placePrediction?: { toPlace(): PlaceLike }; place?: PlaceLike };

type Status = "unconfigured" | "loading" | "loaded" | "ready" | "failed";

interface PropertyMapPickerProps {
  latitude: number | null;
  longitude: number | null;
  onChange: (coords: { latitude: number | null; longitude: number | null }) => void;
  onAddressSelect?: (details: PlaceAddressDetails) => void;
  disabled?: boolean;
  error?: string;
}

const DEFAULT_CENTER = { lat: 17.385044, lng: 78.486671 }; // Hyderabad / Central India
const DEFAULT_ZOOM_WITH_PIN = 16;
const DEFAULT_ZOOM_WITHOUT_PIN = 11;
const INDIA = "in";

const round6 = (value: number) => Number(value.toFixed(6));

function readPosition(position: LatLngLike | null | undefined): LatLngLiteral | null {
  if (!position) return null;
  const lat = typeof position.lat === "function" ? position.lat() : position.lat;
  const lng = typeof position.lng === "function" ? position.lng() : position.lng;
  return { lat, lng };
}

/** Pick a location on a Google map (search, click, drag, or "use my location"). Without a key
 * (NEXT_PUBLIC_GOOGLE_MAPS_API_KEY) or if Google can't be loaded, the manual coordinate fields
 * below the map still work. */
export function PropertyMapPicker({
  latitude,
  longitude,
  onChange,
  onAddressSelect,
  disabled = false,
  error,
}: PropertyMapPickerProps) {
  const t = useTranslations("properties");
  const apiKey = googleMapsKey();

  const mapContainerRef = useRef<HTMLDivElement>(null);
  const searchHostRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<GoogleMap | null>(null);
  const markerRef = useRef<GoogleMarker | null>(null);
  const markerCtorRef = useRef<MarkerCtor | null>(null);
  const geocoderRef = useRef<Geocoder | null>(null);
  const initialCoords = useRef({ latitude, longitude });

  const [status, setStatus] = useState<Status>(apiKey ? "loading" : "unconfigured");
  const [isLocating, setIsLocating] = useState(false);
  const [locateError, setLocateError] = useState("");
  const [manualLat, setManualLat] = useState<string>(latitude !== null ? String(latitude) : "");
  const [manualLng, setManualLng] = useState<string>(longitude !== null ? String(longitude) : "");

  async function reverseGeocode(lat: number, lng: number) {
    const geocoder = geocoderRef.current;
    if (!onAddressSelect || !geocoder) return;
    try {
      const { results } = await geocoder.geocode({ location: { lat, lng } });
      if (!results?.length) return;
      // The most specific street-level result, falling back to the first.
      const best =
        results.find((r) => ["street_address", "premise", "sublocality"].some((type) => r.types?.includes(type))) ??
        results[0];
      onAddressSelect(parseAddressComponents(best.address_components, best.formatted_address));
    } catch {
      // Address auto-fill is a convenience; the pin itself was already set.
    }
  }

  // The map's listeners are created once; they call whatever the latest props and handlers are.
  const latest = useRef({ onChange, onAddressSelect, disabled, reverseGeocode, markerTitle: "", searchPlaceholder: "" });
  useEffect(() => {
    latest.current = {
      onChange,
      onAddressSelect,
      disabled,
      reverseGeocode,
      markerTitle: t("form.markerTitle"),
      searchPlaceholder: t("form.searchLocationPlaceholder"),
    };
  });

  // Keep the typed coordinate fields in step with the pin when it moves from outside the fields.
  const [syncedCoords, setSyncedCoords] = useState({ latitude, longitude });
  if (syncedCoords.latitude !== latitude || syncedCoords.longitude !== longitude) {
    setSyncedCoords({ latitude, longitude });
    setManualLat(latitude !== null ? String(latitude) : "");
    setManualLng(longitude !== null ? String(longitude) : "");
  }

  // 1. Load the Google Maps script.
  useEffect(() => {
    if (!apiKey) return;
    let cancelled = false;
    loadGoogleMaps(apiKey)
      .then(() => {
        if (!cancelled) setStatus("loaded");
      })
      .catch(() => {
        if (!cancelled) setStatus("failed");
      });
    return () => {
      cancelled = true;
    };
  }, [apiKey]);

  // 2. Build the map, the search box and the geocoder once the script is in. Keyed on "script is
  // in" rather than the status itself: the status moves on to "ready" when this finishes, and
  // that must not run this effect's cleanup.
  const scriptLoaded = status === "loaded" || status === "ready";
  useEffect(() => {
    if (!scriptLoaded) return;
    let cancelled = false;
    const host = searchHostRef.current;

    (async () => {
      const [{ Map }, { AdvancedMarkerElement }, { PlaceAutocompleteElement }, { Geocoder: GeocoderCtor }] =
        await Promise.all([
          importMapsLibrary<{ Map: new (el: HTMLElement, options: object) => GoogleMap }>("maps"),
          importMapsLibrary<{ AdvancedMarkerElement: MarkerCtor }>("marker"),
          importMapsLibrary<{ PlaceAutocompleteElement: new (options?: object) => HTMLElement }>("places"),
          importMapsLibrary<{ Geocoder: new () => Geocoder }>("geocoding"),
        ]);
      const container = mapContainerRef.current;
      if (cancelled || !container) return;

      const { latitude: lat0, longitude: lng0 } = initialCoords.current;
      const hasPin = lat0 !== null && lng0 !== null;
      const map = new Map(container, {
        center: hasPin ? { lat: lat0, lng: lng0 } : DEFAULT_CENTER,
        zoom: hasPin ? DEFAULT_ZOOM_WITH_PIN : DEFAULT_ZOOM_WITHOUT_PIN,
        mapId: googleMapsMapId(),
        mapTypeControl: false,
        streetViewControl: false,
        fullscreenControl: true,
        zoomControl: true,
      });

      map.addListener("click", (event) => {
        if (latest.current.disabled || !event.latLng) return;
        const lat = round6(event.latLng.lat());
        const lng = round6(event.latLng.lng());
        latest.current.onChange({ latitude: lat, longitude: lng });
        void latest.current.reverseGeocode(lat, lng);
      });

      const autocomplete = new PlaceAutocompleteElement({ includedRegionCodes: [INDIA] });
      (autocomplete as HTMLElement & { placeholder?: string }).placeholder = latest.current.searchPlaceholder;
      const handleSelect = async (event: Event) => {
        const { placePrediction, place: legacyPlace } = event as PlaceSelectEvent;
        const place = placePrediction?.toPlace() ?? legacyPlace;
        if (!place) return;
        await place.fetchFields({ fields: ["location", "formattedAddress", "addressComponents"] });
        if (!place.location) return;
        const lat = round6(place.location.lat());
        const lng = round6(place.location.lng());
        latest.current.onChange({ latitude: lat, longitude: lng });
        map.panTo({ lat, lng });
        map.setZoom(DEFAULT_ZOOM_WITH_PIN);
        if (place.addressComponents?.length) {
          latest.current.onAddressSelect?.(
            parseAddressComponents(place.addressComponents, place.formattedAddress ?? "")
          );
        } else {
          void latest.current.reverseGeocode(lat, lng);
        }
      };
      autocomplete.addEventListener("gmp-select", handleSelect);
      autocomplete.addEventListener("gmp-placeselect", handleSelect);
      host?.replaceChildren(autocomplete);

      mapRef.current = map;
      markerCtorRef.current = AdvancedMarkerElement;
      geocoderRef.current = new GeocoderCtor();
      setStatus("ready");
    })().catch(() => {
      if (!cancelled) setStatus("failed");
    });

    return () => {
      cancelled = true;
      if (markerRef.current) markerRef.current.map = null;
      markerRef.current = null;
      mapRef.current = null;
      host?.replaceChildren();
    };
  }, [scriptLoaded]);

  // 3. Keep the marker on the pin (and move or remove it when the coordinates change).
  useEffect(() => {
    const map = mapRef.current;
    const Marker = markerCtorRef.current;
    if (status !== "ready" || !map || !Marker) return;

    if (latitude === null || longitude === null) {
      if (markerRef.current) markerRef.current.map = null;
      return;
    }

    const position = { lat: latitude, lng: longitude };
    if (!markerRef.current) {
      const marker = new Marker({
        map,
        position,
        gmpDraggable: !latest.current.disabled,
        title: latest.current.markerTitle,
      });
      marker.addListener("dragend", () => {
        const coords = readPosition(marker.position);
        if (!coords) return;
        const lat = round6(coords.lat);
        const lng = round6(coords.lng);
        latest.current.onChange({ latitude: lat, longitude: lng });
        void latest.current.reverseGeocode(lat, lng);
      });
      markerRef.current = marker;
    } else {
      markerRef.current.position = position;
      markerRef.current.map = map;
      markerRef.current.gmpDraggable = !disabled;
    }

    map.panTo(position);
    if ((map.getZoom() ?? 0) < 14) map.setZoom(DEFAULT_ZOOM_WITH_PIN);
  }, [status, latitude, longitude, disabled]);

  const handleApplyManualCoords = (newLatStr: string, newLngStr: string) => {
    setManualLat(newLatStr);
    setManualLng(newLngStr);

    if (newLatStr.trim() === "" && newLngStr.trim() === "") {
      onChange({ latitude: null, longitude: null });
      return;
    }

    const parsedLat = parseFloat(newLatStr);
    const parsedLng = parseFloat(newLngStr);
    if (
      !isNaN(parsedLat) &&
      !isNaN(parsedLng) &&
      parsedLat >= -90 &&
      parsedLat <= 90 &&
      parsedLng >= -180 &&
      parsedLng <= 180
    ) {
      onChange({ latitude: round6(parsedLat), longitude: round6(parsedLng) });
    }
  };

  const handleLocateMe = () => {
    setLocateError("");
    if (!navigator.geolocation) {
      setLocateError(t("form.locateUnsupported"));
      return;
    }

    setIsLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setIsLocating(false);
        const lat = round6(pos.coords.latitude);
        const lng = round6(pos.coords.longitude);
        onChange({ latitude: lat, longitude: lng });
        void reverseGeocode(lat, lng);
        mapRef.current?.panTo({ lat, lng });
        mapRef.current?.setZoom(DEFAULT_ZOOM_WITH_PIN);
      },
      (err) => {
        setIsLocating(false);
        setLocateError(t("form.locateDenied", { message: err.message }));
      },
      { enableHighAccuracy: true, timeout: 10000 }
    );
  };

  const handleClearPin = () => {
    onChange({ latitude: null, longitude: null });
    setManualLat("");
    setManualLng("");
  };

  const hasPin = latitude !== null && longitude !== null;
  const isReady = status === "ready";

  return (
    <div className="space-y-3.5">
      {/* Header with Title and Status */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-2.5">
        <div>
          <h2 className="text-sm font-bold uppercase tracking-wider text-ink flex items-center gap-1.5">
            <Compass className="size-4 text-accent" />
            {t("form.locationHeading")}
          </h2>
          <p className="text-xs text-ink-muted mt-0.5">{t("form.locationSubtitle")}</p>
        </div>

        {/* Pin status pill */}
        {hasPin ? (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700 border border-emerald-200">
            <CheckCircle2 className="size-3.5 text-emerald-600" />
            {t("form.pinSet", { lat: latitude?.toFixed(4), lng: longitude?.toFixed(4) })}
          </span>
        ) : (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-surface-page px-3 py-1 text-xs font-semibold text-ink-faint border border-border">
            <MapPin className="size-3.5 text-ink-faint" />
            {t("form.noPinSet")}
          </span>
        )}
      </div>

      {/* Maps not configured: say so; the coordinate fields below still work */}
      {status === "unconfigured" && (
        <div className="rounded-xl border border-amber-200 bg-amber-50/80 p-4 text-xs text-amber-900 shadow-sm">
          <div className="flex items-start gap-2.5">
            <KeyRound className="size-4.5 text-amber-700 shrink-0 mt-0.5" />
            <div className="space-y-1">
              <p className="font-bold text-amber-950">{t("form.mapApiKeyMissing")}</p>
              <p className="text-amber-800 leading-relaxed">{t("form.mapApiKeyHelp")}</p>
            </div>
          </div>
        </div>
      )}

      {(status === "loading" || status === "loaded") && (
        <div role="status" className="flex items-center gap-2 text-xs text-ink-muted py-2">
          <LoaderCircle className="size-4 animate-spin text-accent" />
          {t("form.mapLoading")}
        </div>
      )}

      {status === "failed" && (
        <div
          role="alert"
          className="flex items-center gap-2 rounded-xl border border-status-critical/30 bg-status-critical-soft px-3.5 py-2.5 text-xs text-status-critical"
        >
          <AlertCircle className="size-4 shrink-0" />
          {t("form.mapLoadFailed")}
        </div>
      )}

      {/* Search Bar & Quick Action Controls */}
      <div className="flex flex-col sm:flex-row gap-2">
        {/* Google Places search: its element is mounted into the host once Maps is ready */}
        <div className="relative flex-1">
          {!isReady && (
            <>
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-ink-faint" />
              <input
                type="text"
                placeholder={t("form.searchLocationPlaceholder")}
                disabled
                className="w-full rounded-xl border border-border bg-surface-page cursor-not-allowed pl-9 pr-4 py-2 text-xs text-ink placeholder:text-ink-faint outline-none"
              />
            </>
          )}
          <div
            ref={searchHostRef}
            className={isReady ? (disabled ? "pointer-events-none opacity-60" : "") : "hidden"}
          />
        </div>

        {/* Locate me button */}
        <button
          type="button"
          onClick={handleLocateMe}
          disabled={disabled || isLocating}
          className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-border bg-surface-page px-3.5 py-2 text-xs font-semibold text-ink hover:bg-surface-card transition-colors cursor-pointer disabled:opacity-50"
          title={t("form.locateMeTitle")}
        >
          {isLocating ? (
            <LoaderCircle className="size-3.5 animate-spin text-accent" />
          ) : (
            <Navigation className="size-3.5 text-accent" />
          )}
          {t("form.locateMeButton")}
        </button>

        {/* Clear pin button */}
        {hasPin && (
          <button
            type="button"
            onClick={handleClearPin}
            disabled={disabled}
            className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-border bg-surface-page px-3 py-2 text-xs font-semibold text-status-critical hover:bg-red-50 hover:border-red-200 transition-colors cursor-pointer disabled:opacity-50"
            title={t("form.clearPinTitle")}
          >
            <X className="size-3.5" />
            {t("form.clearPinButton")}
          </button>
        )}
      </div>

      {locateError && <p role="alert" className="text-xs text-status-critical">{locateError}</p>}

      {/* Interactive Map Box */}
      <div className="relative w-full h-72 md:h-80 rounded-2xl border border-border overflow-hidden bg-slate-100 shadow-inner">
        <div ref={mapContainerRef} className="size-full" />

        {/* Overlay helper hint */}
        {isReady && (
          <div className="absolute bottom-2.5 left-2.5 z-10 bg-slate-950/70 backdrop-blur-md px-3 py-1.5 rounded-lg text-[11px] text-white flex items-center gap-1.5 shadow-md pointer-events-none">
            <MapPin className="size-3 text-accent shrink-0" />
            <span>{t("form.dragPinHint")}</span>
          </div>
        )}

        {/* Placeholder while there is no interactive map */}
        {!isReady && status !== "loading" && status !== "loaded" && (
          <div className="absolute inset-0 flex flex-col items-center justify-center p-6 text-center bg-slate-50/90 backdrop-blur-xs">
            <div className="size-12 rounded-full bg-blue-50 border border-blue-100 flex items-center justify-center text-accent mb-3">
              <MapPin className="size-6" />
            </div>
            <p className="text-xs font-bold text-ink mb-1">{t("form.locationHeading")}</p>
            <p className="text-[11px] text-ink-muted max-w-sm leading-relaxed mb-3">
              {t("form.locationSubtitle")}
            </p>
            {hasPin && (
              <a
                href={`https://www.google.com/maps/search/?api=1&query=${latitude},${longitude}`}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-[11px] font-semibold text-accent underline hover:text-accent-hover"
              >
                <span>{t("form.viewOnGoogleMaps")}</span>
                <ExternalLink className="size-3" />
              </a>
            )}
          </div>
        )}
      </div>

      {/* Manual Coordinates Grid */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 pt-1">
        <div className="space-y-1">
          <label htmlFor="map-latitude" className="text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
            {t("form.latitudeLabel")} <span className="normal-case text-ink-faint">{t("form.latitudeRange")}</span>
          </label>
          <input
            id="map-latitude"
            type="number"
            step="0.000001"
            min="-90"
            max="90"
            placeholder={t("form.latitudeExample")}
            value={manualLat}
            disabled={disabled}
            onChange={(e) => handleApplyManualCoords(e.target.value, manualLng)}
            className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2 text-xs text-ink outline-none transition-all focus:border-accent focus:ring-4 focus:ring-accent/15"
          />
        </div>

        <div className="space-y-1">
          <label htmlFor="map-longitude" className="text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
            {t("form.longitudeLabel")} <span className="normal-case text-ink-faint">{t("form.longitudeRange")}</span>
          </label>
          <input
            id="map-longitude"
            type="number"
            step="0.000001"
            min="-180"
            max="180"
            placeholder={t("form.longitudeExample")}
            value={manualLng}
            disabled={disabled}
            onChange={(e) => handleApplyManualCoords(manualLat, e.target.value)}
            className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2 text-xs text-ink outline-none transition-all focus:border-accent focus:ring-4 focus:ring-accent/15"
          />
        </div>
      </div>

      {error && <p className="text-xs text-status-critical font-medium">{error}</p>}
    </div>
  );
}
