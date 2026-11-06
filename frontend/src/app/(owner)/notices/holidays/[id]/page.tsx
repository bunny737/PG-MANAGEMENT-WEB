"use client";

import { Suspense, use } from "react";
import { RequirePermission } from "@/components/shared/RequirePermission";
import { FoodHolidayDetail } from "@/features/notices/FoodHolidayDetail";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function FoodHolidayDetailPage({ params }: PageProps) {
  const { id } = use(params);

  return (
    <RequirePermission permission="view_notices">
      <main className="mx-auto w-full max-w-5xl px-4 py-8 md:px-8">
        <Suspense>
          <FoodHolidayDetail id={id} />
        </Suspense>
      </main>
    </RequirePermission>
  );
}
