import { DeleteAccountDocument } from "@/features/marketing/sections/LegalPage";
import { marketingMetadata } from "@/features/marketing/seo";

export const generateMetadata = () => marketingMetadata("deleteAccount");

// The "Delete account URL" given to Google Play: a public page that names the app and developer,
// says what is deleted and kept, and lets the person start the request on the web.
export default function DeleteAccountPage() {
  return <DeleteAccountDocument />;
}
