import type { Metadata } from "next";

// Pure SEO helpers (no next-intl, no fetches) so they can be unit-tested; seo.ts wires in the
// translated text and live data.

export const OG_LOCALE = "en_IN";

/** The share card, served by app/social-card.png/route.tsx (1200x630). */
export const SOCIAL_IMAGE = {
  url: "/social-card.png",
  width: 1200,
  height: 630,
  alt: "PGLive — PG & hostel management software for India",
} as const;

/** Next merges `metadata` objects shallowly, one top-level key at a time: a page that sets
 * `openGraph` or `twitter` REPLACES the layout's whole object. So every page builds the complete
 * objects here and the layout sets neither. The card is listed explicitly too: Next drops the
 * file-convention image once a page sets its own openGraph / twitter. */
export function pageMetadata(input: {
  title: string;
  description: string;
  path: string;
  siteName: string;
}): Metadata {
  const { title, description, path, siteName } = input;
  return {
    title,
    description,
    alternates: { canonical: path },
    openGraph: {
      type: "website",
      siteName,
      locale: OG_LOCALE,
      title,
      description,
      url: path,
      images: [SOCIAL_IMAGE],
    },
    twitter: {
      card: "summary_large_image",
      images: [{ url: SOCIAL_IMAGE.url, alt: SOCIAL_IMAGE.alt }],
      title,
      description,
    },
  };
}

export type Crumb = { name: string; path: string };

const absolute = (origin: string, path: string) => `${origin}${path === "/" ? "" : path}`;

/** BreadcrumbList following the real user path (Home → … → page). */
export function breadcrumbJsonLd(origin: string, trail: Crumb[]): Record<string, unknown> {
  return {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: trail.map((crumb, index) => ({
      "@type": "ListItem",
      position: index + 1,
      name: crumb.name,
      item: absolute(origin, crumb.path),
    })),
  };
}

export function websiteJsonLd(origin: string, name: string): Record<string, unknown> {
  return { "@context": "https://schema.org", "@type": "WebSite", name, url: origin };
}

/** Semantic markup only: Google's software-app rich result needs a real rating or review, which
 * we never invent, so no rich snippet is expected from this. */
export function softwareApplicationJsonLd(input: {
  origin: string;
  name: string;
  offers: Record<string, unknown>[];
  /** Set only when the Play listing is live (site-config drops it otherwise). */
  playStoreUrl: string | null;
}): Record<string, unknown> {
  const { origin, name, offers, playStoreUrl } = input;
  return {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    name,
    applicationCategory: "BusinessApplication",
    // Owner decision 2026-10-25: Android is named before launch; downloadUrl waits for the listing.
    operatingSystem: "Web, Android",
    url: origin,
    ...(playStoreUrl ? { downloadUrl: playStoreUrl } : {}),
    ...(offers.length ? { offers } : {}),
  };
}

/** `lastmod` for the sitemap: the page's own review date, or a newer catalogue `updated_at`
 * for the pages that show prices. An unparsable or future catalogue date is ignored, and the
 * fallback is never "now" (Google only trusts consistently accurate lastmod values). */
export function resolveLastModified(
  pageDate: string,
  catalogUpdatedAt: string | null | undefined,
  now: Date
): Date {
  const own = new Date(`${pageDate}T00:00:00Z`);
  if (!catalogUpdatedAt) return own;
  const updated = new Date(catalogUpdatedAt);
  if (Number.isNaN(updated.getTime()) || updated.getTime() > now.getTime()) return own;
  return updated.getTime() > own.getTime() ? updated : own;
}
