import { PrivacyDocument } from "@/features/marketing/sections/LegalPage";
import { marketingMetadata } from "@/features/marketing/seo";
import { PageBreadcrumb } from "@/components/marketing/PageBreadcrumb";

export const generateMetadata = () => marketingMetadata("privacy");

export default function PrivacyPage() {
  return (
    <>
      <PageBreadcrumb page="privacy" />
      <PrivacyDocument />
    </>
  );
}
