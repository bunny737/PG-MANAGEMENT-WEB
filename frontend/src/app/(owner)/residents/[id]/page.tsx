"use client";

import React, { use } from "react";
import { ResidentProfile } from "@/features/residents/ResidentProfile";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function ResidentDetailPage({ params }: PageProps) {
  const { id } = use(params);

  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-8 md:px-8">
      <ResidentProfile id={id} />
    </main>
  );
}
