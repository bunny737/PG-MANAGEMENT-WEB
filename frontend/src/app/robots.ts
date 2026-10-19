import type { MetadataRoute } from "next";
import { getSiteConfig } from "@/lib/site-config";

// The signed-in app is private and client-guarded, so keep crawlers out of it
// (the root layout also sends noindex). Keep this list in step with src/app/(owner).
const APP_PATHS = [
  "/login",
  "/dashboard",
  "/properties",
  "/residents",
  "/staff",
  "/visitors",
  "/complaints",
  "/financials",
  "/billing",
  "/admissions",
  "/expenses",
  "/reports",
  "/settings",
  "/profile",
  "/more",
];

export default function robots(): MetadataRoute.Robots {
  const { url, env } = getSiteConfig();
  // A staging deploy must never be indexed.
  if (env === "staging") {
    return { rules: { userAgent: "*", disallow: "/" } };
  }
  return {
    rules: { userAgent: "*", allow: "/", disallow: APP_PATHS },
    sitemap: `${url}/sitemap.xml`,
  };
}
