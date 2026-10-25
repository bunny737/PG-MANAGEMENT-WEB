import { AppShowcase } from "@/features/marketing/sections/AppShowcase";
import { marketingMetadata } from "@/features/marketing/seo";
import { PageBreadcrumb } from "@/components/marketing/PageBreadcrumb";

export const generateMetadata = () => marketingMetadata("app");

// Permanent QR target (https://pglive.in/app). Deliberately a landing page, never a
// redirect: desktop visitors can't use a Play link, and an iOS build may follow.
export default function AppPage() {
  return (
    <>
      <PageBreadcrumb page="app" />
      <AppShowcase isPage />
    </>
  );
}
