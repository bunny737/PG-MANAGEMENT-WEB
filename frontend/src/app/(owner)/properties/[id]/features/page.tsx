import { PropertyFeaturesForm } from "@/features/properties/PropertyFeaturesForm";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function PropertyFeaturesPage({ params }: PageProps) {
  const { id } = await params;
  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-8 md:px-8">
      <PropertyFeaturesForm propertyId={id} />
    </main>
  );
}
