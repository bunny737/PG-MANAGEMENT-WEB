import { TermsDocument } from "@/features/marketing/sections/LegalPage";
import { marketingMetadata } from "@/features/marketing/seo";
import { PageBreadcrumb } from "@/components/marketing/PageBreadcrumb";

export const generateMetadata = () => marketingMetadata("terms");

export default function TermsPage() {
  return (
    <>
      <PageBreadcrumb page="terms" />
      <TermsDocument />
    </>
  );
}
