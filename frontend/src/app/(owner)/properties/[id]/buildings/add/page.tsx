import { AddBuildingForm } from "@/features/properties/AddBuildingForm";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function PropertyAddBuildingPage({ params }: PageProps) {
  const { id } = await params;
  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-8 md:px-8">
      <AddBuildingForm propertyId={id} />
    </main>
  );
}
