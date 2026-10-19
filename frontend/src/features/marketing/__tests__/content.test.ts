import { describe, expect, it } from "vitest";
import en from "@/messages/en/marketing.json";
import te from "@/messages/te/marketing.json";
import { FEATURES, FEATURE_GROUPS, HIGHLIGHT_KEYS, SURFACES } from "../content/features";
import { FEATURE_ICONS } from "../featureIcons";

type Tree = Record<string, unknown>;

function keyPaths(node: unknown, prefix = ""): string[] {
  if (Array.isArray(node)) return [`${prefix}[${node.length}]`];
  if (node && typeof node === "object") {
    return Object.entries(node as Tree).flatMap(([key, value]) =>
      keyPaths(value, prefix ? `${prefix}.${key}` : key)
    );
  }
  return [prefix];
}

describe("feature availability matrix", () => {
  it("has unique keys, a state for every surface, and a known group", () => {
    const keys = FEATURES.map((feature) => feature.key);
    expect(new Set(keys).size).toBe(keys.length);
    for (const feature of FEATURES) {
      expect(FEATURE_GROUPS).toContain(feature.group);
      expect(Object.keys(feature.availability).sort()).toEqual([...SURFACES].sort());
    }
  });

  it("has copy in both languages and an icon for every feature", () => {
    for (const feature of FEATURES) {
      for (const catalogue of [en, te]) {
        const item = (catalogue.features.items as Tree)[feature.key] as Tree | undefined;
        expect(item?.title, `${feature.key} title`).toBeTruthy();
        expect(item?.description, `${feature.key} description`).toBeTruthy();
      }
      expect(FEATURE_ICONS[feature.key], `${feature.key} icon`).toBeDefined();
    }
  });

  it("only highlights features that exist and are usable on the owner web", () => {
    for (const key of HIGHLIGHT_KEYS) {
      const feature = FEATURES.find((entry) => entry.key === key);
      expect(feature, key).toBeDefined();
      expect(feature?.availability.ownerWeb).toBe("available");
    }
  });

  it("never marks the Android app as available before launch", () => {
    for (const feature of FEATURES) {
      expect(feature.availability.mobileApp).not.toBe("available");
    }
  });

  it("does not market the unbuilt resident portal as available", () => {
    for (const feature of FEATURES) {
      expect(feature.availability.residentWeb).not.toBe("available");
    }
  });
});

describe("marketing message catalogues", () => {
  it("Telugu mirrors every English key (legal text is still English until counsel reviews a translation)", () => {
    expect(keyPaths(te).sort()).toEqual(keyPaths(en).sort());
  });

  it("keeps the same ICU placeholders in both languages", () => {
    const placeholders = (text: string) => (text.match(/\{(\w+)\}/g) ?? []).sort().join();
    const walk = (a: unknown, b: unknown, path: string) => {
      if (typeof a === "string" && typeof b === "string") {
        expect(placeholders(b), path).toBe(placeholders(a));
      } else if (a && b && typeof a === "object" && typeof b === "object") {
        for (const key of Object.keys(b as Tree)) walk((a as Tree)[key], (b as Tree)[key], `${path}.${key}`);
      }
    };
    walk(en, te, "marketing");
  });

  it("states the access model the site actually offers (no signup claims while it is disabled)", () => {
    expect(en.cta.requestAccess).toMatch(/early access/i);
    expect(JSON.stringify(en)).not.toMatch(/download on the app store|available on ios/i);
  });
});
