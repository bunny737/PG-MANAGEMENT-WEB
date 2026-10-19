import { ContactChannels } from "@/features/marketing/sections/ContactChannels";
import { marketingMetadata } from "@/features/marketing/seo";

export const generateMetadata = () => marketingMetadata("contact");

export default function ContactPage() {
  return <ContactChannels />;
}
