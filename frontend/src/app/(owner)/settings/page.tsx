"use client";

import { RequirePermission } from "@/components/shared/RequirePermission";
import { GlobalSettings } from "@/features/properties/GlobalSettings";

export default function SystemSettingsPage() {
  return (
    <RequirePermission permission="manage_tenant_settings">
      <main className="mx-auto w-full max-w-5xl px-4 py-8 md:px-8">
        <GlobalSettings />
      </main>
    </RequirePermission>
  );
}
