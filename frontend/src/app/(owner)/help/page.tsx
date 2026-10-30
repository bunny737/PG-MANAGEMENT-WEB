"use client";

import { Suspense } from "react";
import { HelpPage } from "@/features/onboarding/HelpPage";

/** Help & tutorials (Module 23) — every staff role; the owner layout already gates staff. */
export default function HelpRoute() {
  return (
    <Suspense>
      <HelpPage />
    </Suspense>
  );
}
