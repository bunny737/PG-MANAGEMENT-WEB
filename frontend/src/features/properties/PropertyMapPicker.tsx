"use client";

import React, { useEffect, useRef, useState, useCallback } from "react";
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

// Global declaration for window.google
declare global {
  interface Window {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    google?: any;
    __initGoogleMapsCallback?: () => void;
  }
}

interface PlaceAddressDetails {
  address?: string;
  city?: string;
  state?: string;
  pincode?: string;
}

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
const STORAGE_KEY = "GMAPS_API_KEY";

function parseGoogleAddressComponents(
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  components: any[] = [],
  formattedAddress = ""
): PlaceAddressDetails {
  let premise = "";
  let street = "";
  let sublocality = "";
  let city = "";
  let state = "";
  let pincode = "";

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  components.forEach((c: any) => {
    const types: string[] = c.types || [];
    if (types.includes("premise") || types.includes("subpremise")) {
      premise = c.long_name;
    } else if (types.includes("street_number") || types.includes("route")) {
      street = street ? `${street}, ${c.long_name}` : c.long_name;
    } else if (
      types.includes("sublocality_level_1") ||
      types.includes("sublocality") ||
      types.includes("neighborhood")
    ) {
      sublocality = sublocality ? `${sublocality}, ${c.long_name}` : c.long_name;
    }

    if (types.includes("locality")) {
      city = c.long_name;
    } else if (!city && (types.includes("administrative_area_level_2") || types.includes("sublocality_level_2"))) {
      city = c.long_name;
    }

    if (types.includes("administrative_area_level_1")) {
      state = c.long_name;
    }

    if (types.includes("postal_code")) {
      pincode = c.long_name.replace(/\D/g, "").slice(0, 6);
    }
  });

  const parts = [premise, street, sublocality].filter(Boolean);
  const detailedAddress = parts.join(", ");

  return {
    address: detailedAddress || formattedAddress || "",
    city,
    state,
    pincode,
  };
}

export function PropertyMapPicker({
  latitude,
  longitude,
  onChange,
  onAddressSelect,
  disabled = false,
  error,
}: PropertyMapPickerProps) {
  const t = useTranslations("properties");

  const mapContainerRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const mapInstanceRef = useRef<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const markerInstanceRef = useRef<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const autocompleteRef = useRef<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const geocoderRef = useRef<any>(null);

  const [apiKey, setApiKey] = useState<string>("");
  const [tempKeyInput, setTempKeyInput] = useState<string>("");
  const [isScriptLoaded, setIsScriptLoaded] = useState<boolean>(false);
  const [isScriptLoading, setIsScriptLoading] = useState<boolean>(false);
  const [loadError, setLoadError] = useState<string>("");
  const [isLocating, setIsLocating] = useState<boolean>(false);
  const [manualLat, setManualLat] = useState<string>(latitude !== null ? String(latitude) : "");
  const [manualLng, setManualLng] = useState<string>(longitude !== null ? String(longitude) : "");

  // Sync internal manual string inputs with incoming props
  useEffect(() => {
    setManualLat(latitude !== null ? String(latitude) : "");
    setManualLng(longitude !== null ? String(longitude) : "");
  }, [latitude, longitude]);

  // Read environment variable or stored key
  useEffect(() => {
    const envKey = process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY || "";
    const storedKey = typeof window !== "undefined" ? localStorage.getItem(STORAGE_KEY) || "" : "";
    const activeKey = envKey || storedKey;
    setApiKey(activeKey);
    setTempKeyInput(activeKey);
  }, []);

  // Dynamically load Google Maps script
  useEffect(() => {
    if (!apiKey) {
      setIsScriptLoaded(false);
      return;
    }

    if (typeof window !== "undefined" && typeof window.google?.maps?.Map === "function") {
      setIsScriptLoaded(true);
      return;
    }

    const scriptId = "google-maps-script-loader";
    const existingScript = document.getElementById(scriptId) as HTMLScriptElement | null;

    window.__initGoogleMapsCallback = () => {
      if (typeof window.google?.maps?.Map === "function") {
        setIsScriptLoaded(true);
        setIsScriptLoading(false);
      }
    };

    if (existingScript) {
      if (typeof window.google?.maps?.Map === "function") {
        setIsScriptLoaded(true);
      } else {
        setIsScriptLoading(true);
      }
      return;
    }

    setIsScriptLoading(true);
    setLoadError("");

    const script = document.createElement("script");
    script.id = scriptId;
    script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(apiKey)}&libraries=places,marker&callback=__initGoogleMapsCallback`;
    script.async = true;
    script.defer = true;

    script.onerror = () => {
      setLoadError("Google Maps failed to load. Please verify your API key and permissions.");
      setIsScriptLoading(false);
    };

    document.head.appendChild(script);
  }, [apiKey]);

  // Reverse geocoding helper using Google Geocoder
  const reverseGeocode = useCallback(
    (lat: number, lng: number) => {
      if (!onAddressSelect || typeof window === "undefined" || !window.google?.maps?.Geocoder) {
        return;
      }

      if (!geocoderRef.current) {
        geocoderRef.current = new window.google.maps.Geocoder();
      }

      geocoderRef.current.geocode(
        { location: { lat, lng } },
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (results: any[], status: string) => {
          if (status === "OK" && results && results.length > 0) {
            // Find most specific street address result, fallback to results[0]
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const best =
              results.find(
                (r: any) =>
                  r.types?.includes("street_address") ||
                  r.types?.includes("premise") ||
                  r.types?.includes("sublocality")
              ) || results[0];
            const parsed = parseGoogleAddressComponents(best.address_components, best.formatted_address);
            onAddressSelect(parsed);
          }
        }
      );
    },
    [onAddressSelect]
  );

  // Update marker position or remove marker
  const updateMarkerPosition = useCallback(
    (lat: number | null, lng: number | null, panTo = false) => {
      if (!mapInstanceRef.current || typeof window.google?.maps?.Marker !== "function") return;

      if (lat !== null && lng !== null) {
        const position = { lat, lng };

        if (!markerInstanceRef.current) {
          markerInstanceRef.current = new window.google.maps.Marker({
            position,
            map: mapInstanceRef.current,
            draggable: !disabled,
            animation: window.google.maps.Animation.DROP,
            title: "PG Property Location",
          });

          markerInstanceRef.current.addListener("dragend", () => {
            const pos = markerInstanceRef.current?.getPosition();
            if (pos) {
              const newLat = Number(pos.lat().toFixed(6));
              const newLng = Number(pos.lng().toFixed(6));
              onChange({ latitude: newLat, longitude: newLng });
              reverseGeocode(newLat, newLng);
            }
          });
        } else {
          markerInstanceRef.current.setPosition(position);
          markerInstanceRef.current.setMap(mapInstanceRef.current);
        }

        if (panTo) {
          mapInstanceRef.current.panTo(position);
          if (mapInstanceRef.current.getZoom() < 14) {
            mapInstanceRef.current.setZoom(DEFAULT_ZOOM_WITH_PIN);
          }
        }
      } else {
        if (markerInstanceRef.current) {
          markerInstanceRef.current.setMap(null);
        }
      }
    },
    [disabled, onChange, reverseGeocode]
  );

  // Initialize Map and Autocomplete once script is loaded
  useEffect(() => {
    if (
      !isScriptLoaded ||
      !mapContainerRef.current ||
      typeof window.google?.maps?.Map !== "function"
    ) {
      return;
    }

    try {
      const initialCenter =
        latitude !== null && longitude !== null ? { lat: latitude, lng: longitude } : DEFAULT_CENTER;
      const initialZoom =
        latitude !== null && longitude !== null ? DEFAULT_ZOOM_WITH_PIN : DEFAULT_ZOOM_WITHOUT_PIN;

      const map = new window.google.maps.Map(mapContainerRef.current, {
        center: initialCenter,
        zoom: initialZoom,
        mapTypeControl: false,
        streetViewControl: false,
        fullscreenControl: true,
        zoomControl: true,
        styles: [
          {
            featureType: "poi",
            elementType: "labels",
            stylers: [{ visibility: "off" }],
          },
        ],
      });

      mapInstanceRef.current = map;

      // Click on map moves/drops pin and auto-fills address details
      map.addListener("click", (e: { latLng: { lat: () => number; lng: () => number } }) => {
        if (disabled) return;
        const clickedLat = Number(e.latLng.lat().toFixed(6));
        const clickedLng = Number(e.latLng.lng().toFixed(6));
        onChange({ latitude: clickedLat, longitude: clickedLng });
        reverseGeocode(clickedLat, clickedLng);
      });

      // Set initial marker if coordinates are present
      if (latitude !== null && longitude !== null) {
        updateMarkerPosition(latitude, longitude, false);
      }

      // Initialize Autocomplete on Search input
      if (
        searchInputRef.current &&
        !autocompleteRef.current &&
        typeof window.google?.maps?.places?.Autocomplete === "function"
      ) {
        const autocomplete = new window.google.maps.places.Autocomplete(searchInputRef.current, {
          fields: ["geometry", "formatted_address", "address_components"],
        });

        autocomplete.addListener("place_changed", () => {
          const place = autocomplete.getPlace();
          if (!place.geometry || !place.geometry.location) return;

          const placeLat = Number(place.geometry.location.lat().toFixed(6));
          const placeLng = Number(place.geometry.location.lng().toFixed(6));

          onChange({ latitude: placeLat, longitude: placeLng });
          map.panTo({ lat: placeLat, lng: placeLng });
          map.setZoom(DEFAULT_ZOOM_WITH_PIN);

          // Parse address components for auto-fill assistance
          if (onAddressSelect) {
            if (place.address_components && place.address_components.length > 0) {
              const parsed = parseGoogleAddressComponents(place.address_components, place.formatted_address);
              onAddressSelect(parsed);
            } else {
              reverseGeocode(placeLat, placeLng);
            }
          }
        });

        autocompleteRef.current = autocomplete;
      }
    } catch (err) {
      console.error("Error initializing Google Map:", err);
    }
  }, [isScriptLoaded]); // eslint-disable-line react-hooks/exhaustive-deps

  // When props (latitude, longitude) change from outside, update marker
  useEffect(() => {
    if (isScriptLoaded && mapInstanceRef.current) {
      updateMarkerPosition(latitude, longitude, true);
    }
  }, [latitude, longitude, isScriptLoaded, updateMarkerPosition]);

  // Handle manual coordinate typing
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
      onChange({
        latitude: Number(parsedLat.toFixed(6)),
        longitude: Number(parsedLng.toFixed(6)),
      });
    }
  };

  // Browser HTML5 Geolocation API
  const handleLocateMe = () => {
    if (!navigator.geolocation) {
      alert("Geolocation is not supported by your browser.");
      return;
    }

    setIsLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setIsLocating(false);
        const lat = Number(pos.coords.latitude.toFixed(6));
        const lng = Number(pos.coords.longitude.toFixed(6));
        onChange({ latitude: lat, longitude: lng });
        reverseGeocode(lat, lng);

        if (mapInstanceRef.current) {
          mapInstanceRef.current.panTo({ lat, lng });
          mapInstanceRef.current.setZoom(DEFAULT_ZOOM_WITH_PIN);
        }
      },
      (err) => {
        setIsLocating(false);
        alert(`Location access denied or unavailable: ${err.message}`);
      },
      { enableHighAccuracy: true, timeout: 10000 }
    );
  };

  // Clear pin
  const handleClearPin = () => {
    onChange({ latitude: null, longitude: null });
    setManualLat("");
    setManualLng("");
    if (searchInputRef.current) {
      searchInputRef.current.value = "";
    }
  };

  // Save manual API key
  const handleSaveApiKey = () => {
    const trimmed = tempKeyInput.trim();
    if (!trimmed) return;
    localStorage.setItem(STORAGE_KEY, trimmed);
    setApiKey(trimmed);
  };

  const hasPin = latitude !== null && longitude !== null;

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

      {/* API Key Missing Notification / Helper */}
      {!apiKey && (
        <div className="rounded-xl border border-amber-200 bg-amber-50/80 p-4 text-xs text-amber-900 shadow-sm space-y-3">
          <div className="flex items-start gap-2.5">
            <KeyRound className="size-4.5 text-amber-700 shrink-0 mt-0.5" />
            <div className="space-y-1">
              <p className="font-bold text-amber-950">{t("form.mapApiKeyMissing")}</p>
              <p className="text-amber-800 leading-relaxed">{t("form.mapApiKeyHelp")}</p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2 pt-1">
            <input
              type="text"
              placeholder={t("form.pasteApiKeyPlaceholder")}
              value={tempKeyInput}
              onChange={(e) => setTempKeyInput(e.target.value)}
              className="flex-1 min-w-[200px] rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-xs text-ink placeholder:text-ink-faint outline-none focus:border-accent focus:ring-2 focus:ring-accent/15"
            />
            <button
              type="button"
              onClick={handleSaveApiKey}
              className="rounded-lg bg-amber-700 px-3.5 py-1.5 text-xs font-bold text-white hover:bg-amber-800 transition-colors cursor-pointer"
            >
              {t("form.applyKey")}
            </button>
          </div>
        </div>
      )}

      {/* Script Loading / Error notification */}
      {isScriptLoading && (
        <div className="flex items-center gap-2 text-xs text-ink-muted py-2">
          <LoaderCircle className="size-4 animate-spin text-accent" />
          Loading Google Maps services...
        </div>
      )}

      {loadError && (
        <div className="flex items-center gap-2 rounded-xl border border-status-critical/30 bg-status-critical-soft px-3.5 py-2.5 text-xs text-status-critical">
          <AlertCircle className="size-4 shrink-0" />
          {loadError}
        </div>
      )}

      {/* Search Bar & Quick Action Controls */}
      <div className="flex flex-col sm:flex-row gap-2">
        {/* Google Places search input */}
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-ink-faint" />
          <input
            ref={searchInputRef}
            type="text"
            placeholder={t("form.searchLocationPlaceholder")}
            disabled={disabled || !isScriptLoaded}
            className="w-full rounded-xl border border-border bg-surface-card pl-9 pr-4 py-2 text-xs text-ink placeholder:text-ink-faint outline-none transition-all focus:border-accent focus:ring-4 focus:ring-accent/15 disabled:bg-surface-page disabled:cursor-not-allowed"
          />
        </div>

        {/* Locate me button */}
        <button
          type="button"
          onClick={handleLocateMe}
          disabled={disabled || isLocating}
          className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-border bg-surface-page px-3.5 py-2 text-xs font-semibold text-ink hover:bg-surface-card transition-colors cursor-pointer disabled:opacity-50"
          title="Detect and center map on current device location"
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
            title="Remove map pin and clear coordinates"
          >
            <X className="size-3.5" />
            {t("form.clearPinButton")}
          </button>
        )}
      </div>

      {/* Interactive Map Box */}
      <div className="relative w-full h-72 md:h-80 rounded-2xl border border-border overflow-hidden bg-slate-100 shadow-inner">
        <div ref={mapContainerRef} className="size-full" />

        {/* Overlay helper hint */}
        {isScriptLoaded && (
          <div className="absolute bottom-2.5 left-2.5 z-10 bg-slate-950/70 backdrop-blur-md px-3 py-1.5 rounded-lg text-[11px] text-white flex items-center gap-1.5 shadow-md pointer-events-none">
            <MapPin className="size-3 text-accent shrink-0" />
            <span>{t("form.dragPinHint")}</span>
          </div>
        )}

        {/* Empty state placeholder when API key is missing */}
        {!apiKey && (
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
                <span>View current pinned location on Google Maps</span>
                <ExternalLink className="size-3" />
              </a>
            )}
          </div>
        )}
      </div>

      {/* Manual Coordinates Grid */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 pt-1">
        <div className="space-y-1">
          <label className="text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
            {t("form.latitudeLabel")} <span className="normal-case text-ink-faint">(–90.0 to 90.0)</span>
          </label>
          <input
            type="number"
            step="0.000001"
            min="-90"
            max="90"
            placeholder="e.g. 17.385044"
            value={manualLat}
            disabled={disabled}
            onChange={(e) => handleApplyManualCoords(e.target.value, manualLng)}
            className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2 text-xs text-ink outline-none transition-all focus:border-accent focus:ring-4 focus:ring-accent/15"
          />
        </div>

        <div className="space-y-1">
          <label className="text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
            {t("form.longitudeLabel")} <span className="normal-case text-ink-faint">(–180.0 to 180.0)</span>
          </label>
          <input
            type="number"
            step="0.000001"
            min="-180"
            max="180"
            placeholder="e.g. 78.486671"
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
