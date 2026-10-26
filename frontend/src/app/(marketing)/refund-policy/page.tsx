import { RefundPolicyDocument } from "@/features/marketing/sections/LegalPage";
import { marketingMetadata } from "@/features/marketing/seo";
import { PageBreadcrumb } from "@/components/marketing/PageBreadcrumb";

export const generateMetadata = () => marketingMetadata("refund");

export default function RefundPolicyPage() {
  return (
    <>
      <PageBreadcrumb page="refund" />
      <RefundPolicyDocument />
    </>
  );
}
