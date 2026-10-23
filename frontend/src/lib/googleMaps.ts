// Loads the Google Maps JavaScript API once per page and hands out its libraries through
// `importLibrary` (the supported way since the API moved to async loading). The key is the
// build-time NEXT_PUBLIC_GOOGLE_MAPS_API_KEY only; it is never read from storage or typed in.

interface MapsGlobal {
  maps?: { importLibrary?: (name: string) => Promise<unknown> };
}

declare global {
  interface Window {
    google?: MapsGlobal;
    __initGoogleMapsCallback?: () => void;
  }
}

const SCRIPT_ID = "google-maps-script-loader";

let loading: Promise<void> | null = null;

/** The key baked in at build time, or "" when maps are not configured. */
export function googleMapsKey(): string {
  return process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY ?? "";
}

/** A Map ID is required for advanced markers. Google's demo ID keeps development working. */
export function googleMapsMapId(): string {
  return process.env.NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID || "DEMO_MAP_ID";
}

const isLoaded = () => typeof window.google?.maps?.importLibrary === "function";

export function loadGoogleMaps(key: string): Promise<void> {
  if (isLoaded()) return Promise.resolve();
  if (loading) return loading;

  loading = new Promise<void>((resolve, reject) => {
    window.__initGoogleMapsCallback = () => resolve();
    const script = document.createElement("script");
    script.id = SCRIPT_ID;
    script.async = true;
    script.src =
      `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(key)}` +
      "&loading=async&v=weekly&callback=__initGoogleMapsCallback";
    script.onerror = () => {
      loading = null;
      script.remove();
      reject(new Error("Google Maps failed to load"));
    };
    document.head.appendChild(script);
  });
  return loading;
}

export async function importMapsLibrary<T>(name: "maps" | "marker" | "places" | "geocoding"): Promise<T> {
  const importLibrary = window.google?.maps?.importLibrary;
  if (!importLibrary) throw new Error("Google Maps is not loaded");
  return (await importLibrary(name)) as T;
}
