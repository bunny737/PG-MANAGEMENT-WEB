import { ContactChannels } from "@/features/marketing/sections/ContactChannels";
import { marketingMetadata } from "@/features/marketing/seo";
import { PageBreadcrumb } from "@/components/marketing/PageBreadcrumb";

export const generateMetadata = () => marketingMetadata("contact");

export default function ContactPage() {
  return (
    <>
      <PageBreadcrumb page="contact" />
      <ContactChannels />
    </>
  );
}
