import { RoomList } from "@/features/properties/RoomList";

interface PageProps {
  params: Promise<{ id: string; floorId: string }>;
}

export default async function PropertyRoomsPage({ params }: PageProps) {
  const { id, floorId } = await params;
  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-8 md:px-8">
      <RoomList propertyId={id} floorId={floorId} />
    </main>
  );
}
