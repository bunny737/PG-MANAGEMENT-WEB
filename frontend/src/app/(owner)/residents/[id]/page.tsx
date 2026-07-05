import { notFound } from "next/navigation";
import { mockResidents } from "@/features/residents/mock-residents";
import { ResidentProfile } from "@/features/residents/ResidentProfile";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function ResidentDetailPage({ params }: PageProps) {
  const { id } = await params;
  const resident = mockResidents.find((r) => r.id === id);

  if (!resident) {
    notFound();
  }

  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-8 md:px-8">
      <ResidentProfile resident={resident} />
    </main>
  );
}
