import { PropertySettingsForm } from "@/features/properties/PropertySettingsForm";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function PropertySettingsPage({ params }: PageProps) {
  const { id } = await params;
  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-8 md:px-8">
      <PropertySettingsForm propertyId={id} />
    </main>
  );
}
