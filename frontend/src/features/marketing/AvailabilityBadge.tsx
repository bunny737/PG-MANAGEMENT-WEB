import { StatusPill, type Tone } from "@/components/shared/StatusPill";
import type { Availability } from "./content/features";

// Colour never carries the meaning alone: every state also has its own text label.
const TONES: Record<Availability, Tone> = {
  available: "good",
  preview: "warn",
  comingSoon: "neutral",
  notPlanned: "neutral",
};

export function AvailabilityBadge({ state, label }: { state: Availability; label: string }) {
  return <StatusPill label={label} tone={TONES[state]} dot={state !== "notPlanned"} />;
}
