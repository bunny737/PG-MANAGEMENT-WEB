import type { OnboardingStep } from "@/lib/api";

/** Where a checklist step's CTA goes, built from the server's `params` (Module 23 contract).
 * Null when the params a route needs are missing — the step is then blocked anyway.
 * Expenses and admissions take `?property=`, which `useActiveProperty()` adopts as the
 * active property, so the page opens scoped to the property the card names. */
export function stepHref(step: OnboardingStep): string | null {
  const { property_id: p, building_id: b, floor_id: f } = step.params;
  switch (step.key) {
    case "add_property":
      return "/properties/add";
    case "add_building":
      return p ? `/properties/${p}/buildings/add` : null;
    case "add_floor":
      return p && b ? `/properties/${p}/buildings/${b}/floors/add` : null;
    case "add_room":
      return p && f ? `/properties/${p}/floors/${f}/rooms/add` : null;
    case "admit_resident":
      return p ? `/admissions?property=${p}` : null;
    case "record_expense":
      return p ? `/expenses?property=${p}` : null;
  }
}
