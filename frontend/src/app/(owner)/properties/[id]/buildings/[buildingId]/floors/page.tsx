import { FloorList } from "@/features/properties/FloorList";

interface PageProps {
  params: Promise<{ id: string; buildingId: string }>;
}

export default async function BuildingFloorsPage({ params }: PageProps) {
  const { id, buildingId } = await params;
  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-8 md:px-8">
      <FloorList propertyId={id} buildingId={buildingId} />
    </main>
  );
}
