import { describe, expect, it } from "vitest";
import { assertLaunchReady, isPlayStoreUrl, parseSiteEnv } from "../site-config.validation";

const READY = {
  SITE_URL: "https://pglive.in",
  COMPANY_NAME: "Acme Technologies Pvt Ltd",
  COMPANY_ADDRESS: "12 MG Road, Hyderabad 500001",
};

describe("parseSiteEnv", () => {
  it("defaults to coming-soon, early-access, production", () => {
    const { config } = parseSiteEnv(READY);
    expect(config.appStatus).toBe("comingSoon");
    expect(config.signupEnabled).toBe(false);
    expect(config.env).toBe("production");
    expect(config.playStoreUrl).toBeNull();
    expect(config.url).toBe("https://pglive.in");
  });

  it("strips trailing slashes and reduces SITE_URL to its origin", () => {
    expect(parseSiteEnv({ ...READY, SITE_URL: "https://pglive.in/some/path/" }).config.url).toBe(
      "https://pglive.in"
    );
  });

  it("enables signup only for an explicit truthy flag", () => {
    expect(parseSiteEnv({ ...READY, SIGNUP_ENABLED: "true" }).config.signupEnabled).toBe(true);
    expect(parseSiteEnv({ ...READY, SIGNUP_ENABLED: "0" }).config.signupEnabled).toBe(false);
    expect(parseSiteEnv({ ...READY, SIGNUP_ENABLED: "" }).config.signupEnabled).toBe(false);
  });

  it("only goes live with a real Play Store https link", () => {
    const live = parseSiteEnv({
      ...READY,
      APP_STATUS: "live",
      PLAY_STORE_URL: "https://play.google.com/store/apps/details?id=com.pgmate.app",
    });
    expect(live.errors).toEqual([]);
    expect(live.config.appStatus).toBe("live");
    expect(live.config.playStoreUrl).toContain("play.google.com");

    const noUrl = parseSiteEnv({ ...READY, APP_STATUS: "live" });
    expect(noUrl.config.appStatus).toBe("comingSoon");
    expect(noUrl.config.playStoreUrl).toBeNull();
    expect(noUrl.errors.join()).toMatch(/PLAY_STORE_URL/);
  });

  it("rejects non-Play and non-https store links", () => {
    expect(isPlayStoreUrl("https://play.google.com/store/apps/details?id=x")).toBe(true);
    expect(isPlayStoreUrl("http://play.google.com/store/apps/details?id=x")).toBe(false);
    expect(isPlayStoreUrl("https://evil.example/play.google.com")).toBe(false);
    expect(isPlayStoreUrl("not a url")).toBe(false);
    expect(isPlayStoreUrl(null)).toBe(false);
  });

  it("rejects an unknown APP_STATUS", () => {
    expect(parseSiteEnv({ ...READY, APP_STATUS: "launched" }).errors.join()).toMatch(/APP_STATUS/);
  });

  it("flags missing or placeholder company identity", () => {
    expect(parseSiteEnv({}).errors).toEqual(
      expect.arrayContaining(["COMPANY_NAME is not set", "COMPANY_ADDRESS is not set"])
    );
    const todo = parseSiteEnv({ ...READY, COMPANY_NAME: "TODO", COMPANY_ADDRESS: "TBD" });
    expect(todo.errors).toHaveLength(2);
  });
});

describe("assertLaunchReady", () => {
  it("passes when identity is set", () => {
    expect(() => assertLaunchReady(READY)).not.toThrow();
  });

  it("fails a production deploy that still has placeholders", () => {
    expect(() => assertLaunchReady({})).toThrow(/not launch-ready/);
    expect(() => assertLaunchReady({ ...READY, COMPANY_NAME: "" })).toThrow(/COMPANY_NAME/);
  });

  it("lets a staging deploy through", () => {
    expect(() => assertLaunchReady({ SITE_ENV: "staging" })).not.toThrow();
  });
});
