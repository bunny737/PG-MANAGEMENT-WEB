import type { Metadata, Viewport } from "next";
import { Inter, Noto_Sans, Noto_Sans_Telugu, Plus_Jakarta_Sans } from "next/font/google";
import { getLocale, getMessages } from "next-intl/server";
import { NextIntlClientProvider } from "next-intl";
import "./globals.css";

// Inter carries UI text — it holds up at the 12–14px sizes most of this app
// runs at far better than a general-purpose face.
const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
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
  title: "PropManager",
  description: "PG/hostel property management",
};

export const viewport: Viewport = {
  themeColor: "#101828",
  width: "device-width",
  initialScale: 1,
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const locale = await getLocale();
  const messages = await getMessages();

  return (
    <html
      lang={locale}
      dir="ltr"
      className={`${inter.variable} ${plusJakarta.variable} ${notoSans.variable} ${notoSansTelugu.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <NextIntlClientProvider messages={messages} locale={locale}>
          {children}
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
