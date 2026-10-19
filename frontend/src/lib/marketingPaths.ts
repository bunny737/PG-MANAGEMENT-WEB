/** Routes of the public marketing site (app/(marketing)). Keep in step with the exclusion list in
 * proxy.ts. The service worker leaves them alone: they are not part of the installed staff app, so
 * they are never cached for offline use (docs/frontend-plan.md §5.1 and §12). */
const MARKETING_PATH = /^\/(?:(?:features|pricing|app|contact|privacy|terms)(?:\/|$)|$)/;

export function isMarketingPath(pathname: string): boolean {
  return MARKETING_PATH.test(pathname);
}
