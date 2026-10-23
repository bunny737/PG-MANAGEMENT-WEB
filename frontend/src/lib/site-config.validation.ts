// Pure parsing/validation of the marketing site's environment config. Kept free
// of Next.js imports so next.config.ts (build gate), instrumentation.ts (startup
// gate) and Vitest can all use it.
//
// Support contacts (email/phone/WhatsApp) are NOT here: a Super Admin owns them
// (PlatformConfig, served by GET /api/v1/support/), so they can change without
// a deploy. This file holds only what the site itself must know.

export type AppStatus = "comingSoon" | "live";
export type SiteEnvName = "production" | "staging";

export interface SiteConfig {
  /** Canonical origin, no trailing slash. */
  url: string;
  env: SiteEnvName;
  /** True once signup/onboarding exists (FE-01); until then the primary CTA is "request early access". */
  signupEnabled: boolean;
  appStatus: AppStatus;
  playStoreUrl: string | null;
  company: { name: string; address: string };
}

export interface SiteConfigResult {
  config: SiteConfig;
  /** Problems that must block a production deploy. Empty when launch-ready. */
  errors: string[];
}

type Env = Record<string, string | undefined>;

const DEFAULT_URL = "https://pglive.in";
// Values that mean "nobody filled this in".
const PLACEHOLDER = /^(|todo|tbd|changeme|your[-_ ]?company.*|company name|address)$/i;

function flag(raw: string | undefined): boolean {
  return ["1", "true", "yes", "on"].includes((raw ?? "").trim().toLowerCase());
}

export function isPlayStoreUrl(raw: string | null | undefined): boolean {
  if (!raw) return false;
  try {
    const url = new URL(raw);
    return url.protocol === "https:" && url.hostname === "play.google.com";
  } catch {
    return false;
  }
}

export function parseSiteEnv(env: Env): SiteConfigResult {
  const errors: string[] = [];

  let url = (env.SITE_URL ?? DEFAULT_URL).trim().replace(/\/+$/, "");
  try {
    const parsed = new URL(url);
    url = parsed.origin;
    if (parsed.protocol !== "https:" && parsed.hostname !== "localhost") {
      errors.push("SITE_URL must be https");
    }
  } catch {
    errors.push("SITE_URL is not a valid URL");
    url = DEFAULT_URL;
  }

  const siteEnv: SiteEnvName = env.SITE_ENV?.trim().toLowerCase() === "staging" ? "staging" : "production";

  const requestedStatus = (env.APP_STATUS ?? "comingSoon").trim();
  const playStoreUrl = env.PLAY_STORE_URL?.trim() || null;
  let appStatus: AppStatus = requestedStatus === "live" ? "live" : "comingSoon";
  if (requestedStatus !== "live" && requestedStatus !== "comingSoon") {
    errors.push('APP_STATUS must be "comingSoon" or "live"');
  }
  if (appStatus === "live" && !isPlayStoreUrl(playStoreUrl)) {
    errors.push("APP_STATUS=live requires PLAY_STORE_URL to be an https://play.google.com/... link");
    // Never show a store badge without a real listing.
    appStatus = "comingSoon";
  }

  const companyName = (env.COMPANY_NAME ?? "").trim();
  const companyAddress = (env.COMPANY_ADDRESS ?? "").trim();
  if (PLACEHOLDER.test(companyName)) errors.push("COMPANY_NAME is not set");
  if (PLACEHOLDER.test(companyAddress)) errors.push("COMPANY_ADDRESS is not set");

  return {
    config: {
      url,
      env: siteEnv,
      signupEnabled: flag(env.SIGNUP_ENABLED),
      appStatus,
      playStoreUrl: appStatus === "live" ? playStoreUrl : null,
      company: { name: companyName, address: companyAddress },
    },
    errors,
  };
}

/** Throws when a production-grade deploy still has placeholder identity/app
 * config. Staging deploys (SITE_ENV=staging) are exempt. */
export function assertLaunchReady(env: Env): void {
  const { config, errors } = parseSiteEnv(env);
  if (config.env === "staging" || errors.length === 0) return;
  throw new Error(
    `Marketing site config is not launch-ready:\n - ${errors.join("\n - ")}\n` +
      "Set these environment variables, or SITE_ENV=staging for a non-public deploy."
  );
}
