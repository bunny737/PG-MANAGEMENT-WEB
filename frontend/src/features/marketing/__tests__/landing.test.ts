import { describe, expect, it } from "vitest";
import en from "@/messages/en/marketing.json";
import { FEATURES } from "../content/features";
import {
  SOLUTION_PAGES,
  SOLUTION_SLUGS,
  SOLUTIONS_HUB_PATH,
  findSolution,
  solutionPath,
} from "../content/landing";

type Copy = (typeof en.solutions.pages)[keyof typeof en.solutions.pages];
const copyFor = (slug: string) => (en.solutions.pages as Record<string, Copy>)[slug];

describe("solution page registry", () => {
  it("has a unique kebab-case slug per page, in step with SOLUTION_SLUGS", () => {
    const slugs = SOLUTION_PAGES.map((page) => page.slug);
    expect(new Set(slugs).size).toBe(slugs.length);
    expect([...slugs].sort()).toEqual([...SOLUTION_SLUGS].sort());
    for (const slug of slugs) expect(slug).toMatch(/^[a-z0-9]+(?:-[a-z0-9]+)*$/);
  });

  it("owns one distinct query cluster per page (no cannibalisation)", () => {
    const clusters = SOLUTION_PAGES.map((page) => page.cluster.toLowerCase());
    expect(new Set(clusters).size).toBe(clusters.length);
  });

  it("uses a real review date", () => {
    for (const page of SOLUTION_PAGES) {
      expect(page.lastReviewed).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      expect(Number.isNaN(new Date(page.lastReviewed).getTime()), page.slug).toBe(false);
    }
  });

  it("builds paths under the hub and finds pages by slug", () => {
    for (const page of SOLUTION_PAGES) {
      expect(solutionPath(page.slug)).toBe(`${SOLUTIONS_HUB_PATH}/${page.slug}`);
      expect(findSolution(page.slug)).toBe(page);
    }
    expect(findSolution("not-a-page")).toBeUndefined();
  });

  // Truthful claims (frontend-plan §12.5): a page may only feature what works on the owner web today.
  it("only features functions that are available on the owner web", () => {
    for (const page of SOLUTION_PAGES) {
      expect(page.featureKeys.length, page.slug).toBeGreaterThan(0);
      for (const key of page.featureKeys) {
        const feature = FEATURES.find((entry) => entry.key === key);
        expect(feature, `${page.slug}: ${key}`).toBeDefined();
        expect(feature?.availability.ownerWeb, `${page.slug}: ${key}`).toBe("available");
      }
    }
  });
});

describe("solution page copy (English, the indexed language)", () => {
  it("is complete for every page", () => {
    for (const page of SOLUTION_PAGES) {
      const copy = copyFor(page.slug);
      expect(copy, page.slug).toBeDefined();
      for (const field of ["breadcrumb", "nav", "eyebrow", "title", "intro", "summary"] as const) {
        expect(copy[field], `${page.slug}.${field}`).toBeTruthy();
      }
      expect(copy.sections.length, `${page.slug} sections`).toBeGreaterThanOrEqual(3);
      for (const section of copy.sections) {
        expect(section.heading && section.body, page.slug).toBeTruthy();
      }
      expect(copy.faq.items.length, `${page.slug} faq`).toBeGreaterThanOrEqual(3);
      for (const item of copy.faq.items) expect(item.q && item.a, page.slug).toBeTruthy();
    }
  });

  it("has search-friendly titles and descriptions, unique across the site", () => {
    const titles = new Set<string>();
    const descriptions = new Set<string>();
    const metas = [en.solutions.hub.meta, ...SOLUTION_PAGES.map((page) => copyFor(page.slug).meta)];
    for (const meta of metas) {
      expect(meta.title.length, meta.title).toBeLessThanOrEqual(65);
      expect(meta.description.length, meta.description).toBeLessThanOrEqual(160);
      expect(meta.description.length, meta.description).toBeGreaterThanOrEqual(70);
      titles.add(meta.title);
      descriptions.add(meta.description);
    }
    for (const home of [en.meta.home, en.meta.features, en.meta.pricing]) {
      titles.add(home.title);
      descriptions.add(home.description);
    }
    expect(titles.size).toBe(metas.length + 3);
    expect(descriptions.size).toBe(metas.length + 3);
  });

  it("does not repeat a section or FAQ across pages (no templated body copy)", () => {
    const bodies = SOLUTION_PAGES.flatMap((page) => copyFor(page.slug).sections.map((s) => s.body));
    const answers = SOLUTION_PAGES.flatMap((page) => copyFor(page.slug).faq.items.map((i) => i.a));
    expect(new Set(bodies).size).toBe(bodies.length);
    // The two-line language answer is allowed to repeat; everything else must be page-specific.
    const repeated = answers.filter((answer, index) => answers.indexOf(answer) !== index);
    expect(repeated.every((answer) => /English and Telugu/.test(answer))).toBe(true);
  });

  // Claims we cannot back today (docs/seo/keyword-map.md): rent is never collected by PGLive, there is
  // no confirmed reminder feature, bed transfers are coming soon, and campuses are out of scope.
  it("makes no claim the product cannot back", () => {
    const text = JSON.stringify(en.solutions.pages);
    expect(text).not.toMatch(/remind/i);
    expect(text).not.toMatch(/(?<!not )collects? (your |the )?rent (for|from) you/i);
    expect(text).not.toMatch(/whatsapp|sms/i);
    expect(copyFor("pg-bed-occupancy").faq.items.some((item) => /coming soon/i.test(item.a))).toBe(true);
    expect(copyFor("pg-rent-tracking").faq.items[0].a).toMatch(/does not collect|No\./);
    expect(copyFor("hostel-management-software").faq.items[0].a).toMatch(/^No\./);
  });
});
