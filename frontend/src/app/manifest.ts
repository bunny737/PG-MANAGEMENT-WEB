import type { MetadataRoute } from "next";

// Brand name of the installed app (mirrors common.brandName in the message files; a manifest
// can't use next-intl, and the brand is not translated).
const APP_NAME = "PropManager";

export default function manifest(): MetadataRoute.Manifest {
  return {
    id: "/",
    name: APP_NAME,
    short_name: APP_NAME,
    description: "PG/hostel property management",
    // The signed-in app, not a marketing page: /login sends an already-signed-in user straight
    // to their first allowed screen (features/auth/RedirectIfSignedIn.tsx).
    start_url: "/login?source=pwa",
    scope: "/",
    display: "standalone",
    orientation: "portrait",
    background_color: "#f4f6fa", // --color-surface-page
    theme_color: "#101828", // --color-surface-inverse; same value as the viewport themeColor
    categories: ["business", "productivity"],
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icons/maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
