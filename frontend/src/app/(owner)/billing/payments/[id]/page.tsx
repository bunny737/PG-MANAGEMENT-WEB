"use client";

import { use } from "react";
import { RequirePermission } from "@/components/shared/RequirePermission";
import { ReceiptView } from "@/features/billing/ReceiptView";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function PaymentReceiptPage({ params }: PageProps) {
  const { id } = use(params);

  return (
    <RequirePermission permission="view_finance">
      <main className="mx-auto w-full max-w-4xl px-4 py-8 md:px-8">
        <ReceiptView id={id} />
      </main>
    </RequirePermission>
  );
}
