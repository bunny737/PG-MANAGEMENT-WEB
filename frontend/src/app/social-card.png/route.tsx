/* eslint-disable i18next/no-literal-string -- static, English-only social card artwork (not app UI) */
import { readFile } from "node:fs/promises";
import path from "node:path";
import { ImageResponse } from "next/og";

const size = { width: 1200, height: 630 };

// Social-share card (og:image and twitter:image, features/marketing/seoCore.ts). It lives at a stable
// URL rather than the opengraph-image file convention, whose hashed URL a page cannot reference and
// which Next drops once a page sets its own openGraph. Colours mirror the design tokens in globals.css.
export async function GET() {
  const mark = await readFile(path.join(process.cwd(), "public/brand/pglive-mark.png"));
  const markSrc = `data:image/png;base64,${mark.toString("base64")}`;
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          padding: 80,
          background: "#101828",
          color: "#ffffff",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 24 }}>
          {/* eslint-disable-next-line @next/next/no-img-element -- ImageResponse renders plain <img> */}
          <img src={markSrc} alt="" width={96} height={96} />
          <div style={{ fontSize: 72, fontWeight: 800 }}>PGLive</div>
        </div>
        <div style={{ marginTop: 40, fontSize: 52, fontWeight: 700, lineHeight: 1.15, maxWidth: 900 }}>
          Run every bed, bill and complaint from one place
        </div>
        <div style={{ marginTop: 28, fontSize: 30, color: "#9aa6ba" }}>
          PG & hostel management software for India · pglive.in
        </div>
      </div>
    ),
    // Short cache: the URL is stable, so a redesigned card must reach crawlers within a day.
    { ...size, headers: { "Cache-Control": "public, max-age=86400" } }
  );
}
