import { AddFloorForm } from "@/features/properties/AddFloorForm";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function PropertyAddFloorPage({ params }: PageProps) {
  const { id } = await params;
  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-8 md:px-8">
      <AddFloorForm propertyId={id} />
    </main>
  );
}
