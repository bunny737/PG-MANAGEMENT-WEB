// Single source of truth for what the site claims is usable, per product surface.
// Only keys and machine-readable states live here; every label and description is
// in messages/<locale>/marketing.json under `features.items.<key>` (invariant 7).
//
// Review this file whenever a frontend task in docs/frontend-plan.md §7 changes
// status — marketing must never run ahead of what a user can actually open.
//   available  usable today
//   preview    partly built / early access, or a concept preview
//   comingSoon planned, not usable yet
//   notPlanned not applicable to this surface

export type Surface = "ownerWeb" | "residentWeb" | "mobileApp";
export type Availability = "available" | "preview" | "comingSoon" | "notPlanned";
export type FeatureGroup = "properties" | "residents" | "money" | "operations" | "platform";

export interface FeatureEntry {
  key: string;
  group: FeatureGroup;
  availability: Record<Surface, Availability>;
}

export const SURFACES: readonly Surface[] = ["ownerWeb", "residentWeb", "mobileApp"];
export const FEATURE_GROUPS: readonly FeatureGroup[] = [
  "properties",
  "residents",
  "money",
  "operations",
  "platform",
];

const a = (
  ownerWeb: Availability,
  residentWeb: Availability,
  mobileApp: Availability
): Record<Surface, Availability> => ({ ownerWeb, residentWeb, mobileApp });

export const FEATURES: readonly FeatureEntry[] = [
  // Properties
  { key: "propertySetup", group: "properties", availability: a("preview", "notPlanned", "comingSoon") },
  { key: "amenities", group: "properties", availability: a("available", "notPlanned", "comingSoon") },
  { key: "dashboard", group: "properties", availability: a("available", "notPlanned", "preview") },
  // Residents
  { key: "residents", group: "residents", availability: a("available", "notPlanned", "comingSoon") },
  { key: "admissions", group: "residents", availability: a("preview", "notPlanned", "comingSoon") },
  { key: "allocations", group: "residents", availability: a("comingSoon", "notPlanned", "comingSoon") },
  { key: "depositsExit", group: "residents", availability: a("comingSoon", "notPlanned", "comingSoon") },
  // Money
  { key: "billing", group: "money", availability: a("available", "comingSoon", "preview") },
  { key: "payments", group: "money", availability: a("available", "comingSoon", "comingSoon") },
  { key: "discounts", group: "money", availability: a("available", "notPlanned", "comingSoon") },
  { key: "expenses", group: "money", availability: a("available", "notPlanned", "comingSoon") },
  // Operations
  { key: "complaints", group: "operations", availability: a("preview", "comingSoon", "preview") },
  { key: "visitors", group: "operations", availability: a("available", "comingSoon", "comingSoon") },
  { key: "staff", group: "operations", availability: a("available", "notPlanned", "comingSoon") },
  // Platform
  { key: "reports", group: "platform", availability: a("available", "notPlanned", "comingSoon") },
  { key: "languages", group: "platform", availability: a("available", "comingSoon", "comingSoon") },
  { key: "subscription", group: "platform", availability: a("available", "notPlanned", "notPlanned") },
];

/** Keys shown as highlights on the home page. */
export const HIGHLIGHT_KEYS: readonly string[] = [
  "billing",
  "payments",
  "residents",
  "dashboard",
  "amenities",
  "reports",
];

export function featuresInGroup(group: FeatureGroup): FeatureEntry[] {
  return FEATURES.filter((feature) => feature.group === group);
}
