"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { RequirePermission } from "@/components/shared/RequirePermission";
import { GlobalSettings } from "@/features/properties/GlobalSettings";

const SECURITY_TAB = "security";

/** `?tab=security` (linked from the profile page) opens Account & Security directly. */
function SettingsContent() {
  const tab = useSearchParams().get("tab");
  const initialTab = tab === SECURITY_TAB ? SECURITY_TAB : undefined;
  return <GlobalSettings initialTab={initialTab} />;
}

export default function SystemSettingsPage() {
  return (
    <RequirePermission permission="manage_tenant_settings">
      <main className="mx-auto w-full max-w-5xl px-4 py-8 md:px-8">
        <Suspense fallback={null}>
          <SettingsContent />
        </Suspense>
      </main>
    </RequirePermission>
  );
}
