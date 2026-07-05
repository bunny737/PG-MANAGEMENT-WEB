import { BedDetails } from "@/features/properties/BedDetails";

interface PageProps {
  params: Promise<{ id: string; floorId: string; roomId: string; bedId: string }>;
}

export default async function PropertyBedDetailPage({ params }: PageProps) {
  const { id, floorId, roomId, bedId } = await params;
  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-8 md:px-8">
      <BedDetails propertyId={id} floorId={floorId} roomId={roomId} bedId={bedId} />
    </main>
  );
}
