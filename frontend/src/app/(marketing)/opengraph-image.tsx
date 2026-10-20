/* eslint-disable i18next/no-literal-string -- static, English-only social card artwork (not app UI) */
import { readFile } from "node:fs/promises";
import path from "node:path";
import { ImageResponse } from "next/og";

export const alt = "PGLive — PG & hostel management software for India";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

// Social-share card. Colours mirror the design tokens in globals.css.
export default async function OpenGraphImage() {
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
    size
  );
}
