import { breadcrumbForPage, type MarketingPage } from "@/features/marketing/seo";
import { JsonLd } from "./JsonLd";

/** Home → page BreadcrumbList structured data for a marketing page (renders nothing visible). */
export async function PageBreadcrumb({ page }: { page: Exclude<MarketingPage, "home"> }) {
  return <JsonLd data={await breadcrumbForPage(page)} />;
}
