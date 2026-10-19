import type { MetadataRoute } from "next";
import { MARKETING_PATHS } from "@/features/marketing/seo";
import { getSiteConfig } from "@/lib/site-config";

export default function sitemap(): MetadataRoute.Sitemap {
  const { url } = getSiteConfig();
  return MARKETING_PATHS.map((path) => ({
    url: `${url}${path === "/" ? "" : path}`,
    changeFrequency: path === "/pricing" || path === "/app" ? "weekly" : "monthly",
    priority: path === "/" ? 1 : path === "/privacy" || path === "/terms" ? 0.3 : 0.8,
  }));
}
