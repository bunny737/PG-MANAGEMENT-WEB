import { RefundPolicyDocument } from "@/features/marketing/sections/LegalPage";
import { marketingMetadata } from "@/features/marketing/seo";

export const generateMetadata = () => marketingMetadata("refund");

export default function RefundPolicyPage() {
  return <RefundPolicyDocument />;
}
