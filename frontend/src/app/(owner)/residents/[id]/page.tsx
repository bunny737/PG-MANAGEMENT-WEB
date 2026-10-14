"use client";

import React, { use } from "react";
import { RequirePermission } from "@/components/shared/RequirePermission";
import { ResidentProfile } from "@/features/residents/ResidentProfile";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function ResidentDetailPage({ params }: PageProps) {
  const { id } = use(params);

  return (
    <RequirePermission permission="view_resident_profile">
      <main className="mx-auto w-full max-w-5xl px-4 py-8 md:px-8">
        <ResidentProfile id={id} />
      </main>
    </RequirePermission>
  );
}
