import type { Metadata, Viewport } from "next";
import { Inter, Noto_Sans, Noto_Sans_Telugu, Plus_Jakarta_Sans, Roboto } from "next/font/google";
import { getLocale, getMessages } from "next-intl/server";
import { NextIntlClientProvider } from "next-intl";
import { getLocaleDirection } from "@/i18n/config";
import { PwaRegister } from "@/features/pwa/PwaRegister";
import "./globals.css";

// Inter carries UI text — it holds up at the 12–14px sizes most of this app
// runs at far better than a general-purpose face.
const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  display: "swap",
});

// Roboto is the phone UI's face, so the installed app reads like the Android (Material) app.
// Applied only below the md breakpoint, via .phone-ui in globals.css.
const roboto = Roboto({
  variable: "--font-roboto",
  subsets: ["latin"],
  weight: ["400", "500", "700"],
  display: "swap",
});

// Plus Jakarta Sans is the display voice: headings, money figures, stat values.
const plusJakarta = Plus_Jakarta_Sans({
  variable: "--font-plus-jakarta",
  subsets: ["latin"],
  display: "swap",
});

// Noto Sans handles Latin and Devanagari (Hindi, V2) subsets.
const notoSans = Noto_Sans({
  variable: "--font-noto-sans",
  subsets: ["latin", "devanagari"],
  display: "swap",
});

// Telugu is a separate font family from Google — the base Noto Sans has no
// Telugu subset. Active in MVP alongside English (owner decision 2026-08-11).
// Noto_Sans_Tamil / Noto_Sans_Malayalam join the same way when ta/ml go active (V3).
const notoSansTelugu = Noto_Sans_Telugu({
  variable: "--font-noto-sans-telugu",
  subsets: ["telugu"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "PGLive",
  description: "PG/hostel property management",
  // The signed-in app must never be indexed. The public marketing pages opt back
  // in from their own layout (app/(marketing)/layout.tsx).
  robots: { index: false, follow: false },
  // iOS ignores most of the manifest: these make "Add to Home Screen" open standalone
  // (no Safari chrome) with the right title and icon. The manifest link itself is generated
  // from app/manifest.ts. statusBarStyle "default" keeps the page below the status bar with
  // dark text; "black-translucent" would draw white clock/battery over our light background.
  applicationName: "PGLive",
  appleWebApp: { capable: true, title: "PGLive", statusBarStyle: "default" },
  icons: { apple: "/icons/apple-touch-icon.png" },
  formatDetection: { telephone: false },
};

export const viewport: Viewport = {
  themeColor: "#fbf8ff", // --color-m3-surface: the phone top bar, so the status bar blends into it
  width: "device-width",
  initialScale: 1,
  // Extend to the screen edges so the bottom nav can fill behind the home indicator and pad
  // itself with env(safe-area-inset-bottom).
  viewportFit: "cover",
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const locale = await getLocale();
  // The marketing copy is only rendered by server components, so keep it out of
  // the payload every signed-in page ships to the browser.
  const { marketing: _marketing, ...messages } = await getMessages();
  void _marketing;
  const dir = getLocaleDirection(locale);

  return (
    <html
      lang={locale}
      dir={dir}
      className={`${inter.variable} ${plusJakarta.variable} ${roboto.variable} ${notoSans.variable} ${notoSansTelugu.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <NextIntlClientProvider messages={messages} locale={locale}>
          {children}
          <PwaRegister />
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
