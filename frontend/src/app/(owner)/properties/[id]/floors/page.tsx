import { FloorList } from "@/features/properties/FloorList";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function PropertyFloorsPage({ params }: PageProps) {
  const { id } = await params;
  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-8 md:px-8">
      <FloorList propertyId={id} />
    </main>
  );
}
