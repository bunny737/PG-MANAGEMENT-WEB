"use client";

import { Suspense } from "react";
import { RequirePermission } from "@/components/shared/RequirePermission";
import { NoticesTabs } from "@/features/notices/NoticesTabs";

export default function NoticesRoute() {
  return (
    <RequirePermission permission="view_notices">
      <main className="mx-auto w-full max-w-6xl px-4 py-8 md:px-8">
        <Suspense>
          <NoticesTabs />
        </Suspense>
      </main>
    </RequirePermission>
  );
}
