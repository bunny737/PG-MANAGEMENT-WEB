import { TermsDocument } from "@/features/marketing/sections/LegalPage";
import { marketingMetadata } from "@/features/marketing/seo";

export const generateMetadata = () => marketingMetadata("terms");

export default function TermsPage() {
  return <TermsDocument />;
}
