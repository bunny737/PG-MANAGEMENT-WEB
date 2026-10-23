import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

// The loader keeps module state (the in-flight load), so each test starts from a fresh module.
async function freshLoader() {
  vi.resetModules();
  return import("../googleMaps");
}

const scripts = () => Array.from(document.head.querySelectorAll<HTMLScriptElement>("script#google-maps-script-loader"));

describe("googleMaps loader", () => {
  beforeEach(() => {
    delete window.google;
    delete window.__initGoogleMapsCallback;
    document.head.querySelectorAll("script").forEach((el) => el.remove());
    localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  test("injects one async script with the key, async loading and a callback; resolves when it fires", async () => {
    const { loadGoogleMaps } = await freshLoader();
    const first = loadGoogleMaps("key with/odd&chars");
    const second = loadGoogleMaps("key with/odd&chars");

    expect(scripts()).toHaveLength(1);
    const url = new URL(scripts()[0].src);
    expect(url.origin + url.pathname).toBe("https://maps.googleapis.com/maps/api/js");
    expect(url.searchParams.get("key")).toBe("key with/odd&chars");
    expect(url.searchParams.get("loading")).toBe("async");
    expect(url.searchParams.get("callback")).toBe("__initGoogleMapsCallback");
    // No legacy library list: libraries come from importLibrary.
    expect(url.searchParams.get("libraries")).toBeNull();

    window.__initGoogleMapsCallback?.();
    await expect(first).resolves.toBeUndefined();
    await expect(second).resolves.toBeUndefined();
  });

  test("a failed load rejects and can be retried", async () => {
    const { loadGoogleMaps } = await freshLoader();
    const attempt = loadGoogleMaps("k");
    scripts()[0].onerror?.(new Event("error"));
    await expect(attempt).rejects.toThrow();
    expect(scripts()).toHaveLength(0);

    void loadGoogleMaps("k");
    expect(scripts()).toHaveLength(1);
  });

  test("resolves at once, without a script, when Maps is already on the page", async () => {
    const { loadGoogleMaps } = await freshLoader();
    window.google = { maps: { importLibrary: vi.fn() } };
    await loadGoogleMaps("k");
    expect(scripts()).toHaveLength(0);
  });

  test("the key comes from the build-time env only, never from storage", async () => {
    localStorage.setItem("GMAPS_API_KEY", "from-storage");
    vi.stubEnv("NEXT_PUBLIC_GOOGLE_MAPS_API_KEY", "");
    const unset = await freshLoader();
    expect(unset.googleMapsKey()).toBe("");

    vi.stubEnv("NEXT_PUBLIC_GOOGLE_MAPS_API_KEY", "from-env");
    const set = await freshLoader();
    expect(set.googleMapsKey()).toBe("from-env");
  });

  test("the Map ID falls back to Google's demo ID", async () => {
    vi.stubEnv("NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID", "");
    expect((await freshLoader()).googleMapsMapId()).toBe("DEMO_MAP_ID");
    vi.stubEnv("NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID", "abc123");
    expect((await freshLoader()).googleMapsMapId()).toBe("abc123");
  });

  test("importMapsLibrary refuses to run before Maps is loaded", async () => {
    const { importMapsLibrary } = await freshLoader();
    await expect(importMapsLibrary("maps")).rejects.toThrow();
  });
});
