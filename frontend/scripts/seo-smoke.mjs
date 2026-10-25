// Built-server SEO smoke test: checks what Next actually emits (not what the metadata helpers
// return), so a shallow-merge or routing regression is caught.
//
//   npm run build && npm run start      # or point BASE_URL at a deployed site
//   BASE_URL=http://localhost:3000 npm run seo:smoke
//   BASE_URL=https://www.pglive.in API_URL=https://api.pglive.in npm run seo:smoke
//
// The sitemap lists URLs on SITE_URL's origin; each is fetched from BASE_URL instead, so the
// same run works against localhost.
import { JSDOM } from "jsdom";

const BASE_URL = (process.env.BASE_URL ?? "http://localhost:3000").replace(/\/+$/, "");
const API_URL = process.env.API_URL?.replace(/\/+$/, "");

// Paths that must answer 404 (one unknown slug per landing family joins this list as they ship).
const MUST_404 = ["/features/__seo-smoke-404__"];

const failures = [];
const check = (ok, message) => {
  if (!ok) failures.push(message);
};

const get = (url) => fetch(url, { redirect: "manual", headers: { "user-agent": "seo-smoke" } });
const rebase = (url) => {
  const { pathname, search } = new URL(url);
  return `${BASE_URL}${pathname}${search}`;
};
const meta = (doc, selector) => doc.querySelector(selector)?.getAttribute("content") ?? null;

async function checkImage(label, url) {
  if (!url) return check(false, `${label}: missing`);
  const res = await get(rebase(url));
  check(res.status === 200, `${label}: ${url} returned ${res.status}`);
  check(
    (res.headers.get("content-type") ?? "").startsWith("image/"),
    `${label}: ${url} is ${res.headers.get("content-type")}, not an image`
  );
}

async function checkPage(sitemapUrl) {
  const path = new URL(sitemapUrl).pathname;
  const res = await get(rebase(sitemapUrl));
  const at = (message) => `${path}: ${message}`;

  check(res.status === 200, at(`status ${res.status}, expected 200 without a redirect`));
  check(!res.headers.get("location"), at("redirects"));
  check(!res.headers.get("set-cookie"), at("sets a cookie (marketing pages must stay cookie-free)"));
  if (res.status !== 200) return;

  const doc = new JSDOM(await res.text()).window.document;

  const canonical = doc.querySelector('link[rel="canonical"]')?.getAttribute("href");
  check(canonical === sitemapUrl, at(`canonical is ${canonical}, expected ${sitemapUrl}`));

  const robots = (meta(doc, 'meta[name="robots"]') ?? "").replace(/\s+/g, "");
  check(robots === "index,follow", at(`robots is "${robots}", expected index,follow`));

  check(!!doc.querySelector("title")?.textContent?.trim(), at("no <title>"));
  check(!!meta(doc, 'meta[name="description"]'), at("no meta description"));
  check(meta(doc, 'meta[property="og:site_name"]'), at("no og:site_name"));
  check(meta(doc, 'meta[property="og:type"]') === "website", at("og:type is not website"));
  check(meta(doc, 'meta[property="og:locale"]') === "en_IN", at("og:locale is not en_IN"));
  check(meta(doc, 'meta[name="twitter:card"]') === "summary_large_image", at("twitter:card missing"));
  check(!!meta(doc, 'meta[name="twitter:title"]'), at("no twitter:title"));

  const ogImage = meta(doc, 'meta[property="og:image"]');
  const twitterImage = meta(doc, 'meta[name="twitter:image"]');
  check(ogImage?.startsWith("http"), at("og:image is not absolute"));
  await checkImage(at("og:image"), ogImage);
  await checkImage(at("twitter:image"), twitterImage);

  check(doc.querySelectorAll("h1").length === 1, at(`${doc.querySelectorAll("h1").length} <h1> elements, expected 1`));

  const blocks = [...doc.querySelectorAll('script[type="application/ld+json"]')];
  check(blocks.length > 0, at("no JSON-LD"));
  for (const block of blocks) {
    try {
      JSON.parse(block.textContent ?? "");
    } catch {
      check(false, at("JSON-LD does not parse"));
    }
  }
}

const sitemapRes = await get(`${BASE_URL}/sitemap.xml`);
check(sitemapRes.status === 200, `/sitemap.xml returned ${sitemapRes.status}`);
const urls = [...(await sitemapRes.text()).matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => m[1]);
check(urls.length > 0, "sitemap lists no URLs");

for (const url of urls) await checkPage(url);

for (const path of MUST_404) {
  const res = await get(`${BASE_URL}${path}`);
  check(res.status === 404, `${path}: status ${res.status}, expected 404`);
}

const robotsTxt = await (await get(`${BASE_URL}/robots.txt`)).text();
check(/Sitemap:\s*\S+\/sitemap\.xml/i.test(robotsTxt), "robots.txt has no Sitemap line (expected on a production build)");

if (API_URL) {
  const res = await get(`${API_URL}/health/`);
  const tag = res.headers.get("x-robots-tag") ?? "";
  check(/noindex/i.test(tag), `${API_URL}/health/ sends X-Robots-Tag "${tag}", expected noindex`);
}

if (failures.length) {
  console.error(`SEO smoke: ${failures.length} problem(s)\n - ${failures.join("\n - ")}`);
  process.exit(1);
}
console.log(`SEO smoke OK: ${urls.length} pages checked against ${BASE_URL}`);
