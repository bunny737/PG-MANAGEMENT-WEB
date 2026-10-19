// Regenerates public/icons/*.png from the same Building2 mark the app header uses
// (features/dashboard/DashboardHeader.tsx) on the accent gradient. Run after a rebrand:
//   node scripts/generate-pwa-icons.mjs
// Uses `sharp`, which ships with Next.js, so no extra dependency.

import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import sharp from "sharp";

const outDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../public/icons");
mkdirSync(outDir, { recursive: true });

// lucide-react `building-2` geometry (24x24 grid, stroke icon).
const GLYPH = `
  <path d="M10 12h4"/><path d="M10 8h4"/><path d="M14 21v-3a2 2 0 0 0-4 0v3"/>
  <path d="M6 10H4a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-2"/>
  <path d="M6 21V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v16"/>`;

/**
 * @param rounded  true: transparent corners (the "any" purpose); false: full-bleed square,
 *                 which maskable icons and iOS home-screen icons require (the OS applies the mask).
 * @param glyphPx  rendered glyph size on the 512 canvas; maskable keeps it inside the 80% safe zone.
 */
function svg({ rounded, glyphPx }) {
  const scale = glyphPx / 24;
  const offset = (512 - glyphPx) / 2;
  return Buffer.from(`
<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#4f46e5"/><stop offset="1" stop-color="#4338ca"/>
    </linearGradient>
  </defs>
  <rect width="512" height="512" rx="${rounded ? 112 : 0}" fill="url(#g)"/>
  <g transform="translate(${offset} ${offset}) scale(${scale})" fill="none" stroke="#fff"
     stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${GLYPH}</g>
</svg>`);
}

const targets = [
  { file: "icon-192.png", size: 192, rounded: true, glyphPx: 288 },
  { file: "icon-512.png", size: 512, rounded: true, glyphPx: 288 },
  { file: "maskable-512.png", size: 512, rounded: false, glyphPx: 232 },
  { file: "apple-touch-icon.png", size: 180, rounded: false, glyphPx: 272 },
];

for (const { file, size, rounded, glyphPx } of targets) {
  await sharp(svg({ rounded, glyphPx }), { density: 384 }).resize(size, size).png().toFile(path.join(outDir, file));
  console.log("wrote", file);
}
