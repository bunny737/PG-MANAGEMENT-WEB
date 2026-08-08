import type { Metadata, Viewport } from "next";
import { Inter, Noto_Sans, Plus_Jakarta_Sans } from "next/font/google";
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

// Noto Sans stays in the stack (not as the primary face) because it covers
// Devanagari/Telugu/Tamil/Malayalam — neither Latin font above does. Browsers
// fall back per glyph, so hi/te/ta/ml text still renders once those locales
// are added (PRD §11 / §6 i18n).
const notoSans = Noto_Sans({
  variable: "--font-noto-sans",
  subsets: ["latin"],
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

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${plusJakarta.variable} ${notoSans.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
