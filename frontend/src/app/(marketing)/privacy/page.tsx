import { PrivacyDocument } from "@/features/marketing/sections/LegalPage";
import { marketingMetadata } from "@/features/marketing/seo";

export const generateMetadata = () => marketingMetadata("privacy");

export default function PrivacyPage() {
  return <PrivacyDocument />;
}
