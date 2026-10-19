import { afterEach, describe, expect, test, vi } from "vitest";
import { getInstallState, promptInstall } from "../pwa";
import { triggerDownload } from "../download";

const IPHONE_SAFARI =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1";
// WhatsApp / Instagram webviews omit the trailing "Safari/…" token.
const IPHONE_IN_APP =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram 320.0";
const ANDROID_CHROME =
  "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36";

function stubNavigator(overrides: Record<string, unknown>) {
  vi.stubGlobal("navigator", { userAgent: ANDROID_CHROME, platform: "Linux", maxTouchPoints: 5, ...overrides });
}

function stubDisplayMode(standalone: boolean) {
  vi.stubGlobal("matchMedia", () => ({ matches: standalone }));
  window.matchMedia = (() => ({ matches: standalone })) as unknown as typeof window.matchMedia;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("install state", () => {
  test("iOS Safari gets instructions, since iOS has no install prompt", () => {
    stubDisplayMode(false);
    stubNavigator({ userAgent: IPHONE_SAFARI, platform: "iPhone" });
    expect(getInstallState()).toBe("ios");
  });

  test("an iOS in-app browser is told to open Safari instead", () => {
    stubDisplayMode(false);
    stubNavigator({ userAgent: IPHONE_IN_APP, platform: "iPhone" });
    expect(getInstallState()).toBe("ios-in-app");
  });

  test("iPadOS, which reports itself as a Mac, is still detected as iOS", () => {
    stubDisplayMode(false);
    stubNavigator({ userAgent: IPHONE_SAFARI.replace("iPhone", "Macintosh"), platform: "MacIntel", maxTouchPoints: 5 });
    expect(getInstallState()).toBe("ios");
  });

  test("running as an installed app (iOS navigator.standalone or display-mode) is 'installed'", () => {
    stubDisplayMode(false);
    stubNavigator({ userAgent: IPHONE_SAFARI, platform: "iPhone", standalone: true });
    expect(getInstallState()).toBe("installed");

    stubDisplayMode(true);
    stubNavigator({ userAgent: ANDROID_CHROME });
    expect(getInstallState()).toBe("installed");
  });

  test("a browser without an install prompt and not iOS is unsupported", () => {
    stubDisplayMode(false);
    stubNavigator({ userAgent: ANDROID_CHROME });
    expect(getInstallState()).toBe("unsupported");
  });

  test("beforeinstallprompt makes the app installable, and the prompt is single-use", async () => {
    stubDisplayMode(false);
    stubNavigator({ userAgent: ANDROID_CHROME });

    const prompt = vi.fn(async () => {});
    const event = Object.assign(new Event("beforeinstallprompt", { cancelable: true }), {
      prompt,
      userChoice: Promise.resolve({ outcome: "accepted" as const }),
    });
    window.dispatchEvent(event);

    expect(event.defaultPrevented).toBe(true); // we show our own button, not the mini-infobar
    expect(getInstallState()).toBe("installable");

    expect(await promptInstall()).toBe("accepted");
    expect(prompt).toHaveBeenCalledTimes(1);
    expect(getInstallState()).toBe("unsupported");
    expect(await promptInstall()).toBe("unavailable");
  });
});

describe("triggerDownload", () => {
  const blob = new Blob(["%PDF"], { type: "application/pdf" });
  const payload = { blob, filename: "receipt.pdf" };

  function stubAnchor() {
    const click = vi.fn();
    vi.spyOn(document, "createElement").mockReturnValue({ click } as unknown as HTMLAnchorElement);
    vi.stubGlobal("URL", { createObjectURL: () => "blob:x", revokeObjectURL: () => {} });
    return click;
  }

  function iosStandalone(share: (data: ShareData) => Promise<void>) {
    stubDisplayMode(true);
    stubNavigator({ userAgent: IPHONE_SAFARI, platform: "iPhone", standalone: true, share, canShare: () => true });
  }

  test("installed iOS app: uses the share sheet, not the anchor", async () => {
    const click = stubAnchor();
    const share = vi.fn(async () => {});
    iosStandalone(share);
    await triggerDownload(payload);
    expect(share).toHaveBeenCalledTimes(1);
    expect(click).not.toHaveBeenCalled();
  });

  test("installed iOS app: cancelling the share sheet is not an error and does not also download", async () => {
    const click = stubAnchor();
    iosStandalone(async () => {
      throw new DOMException("cancelled", "AbortError");
    });
    await expect(triggerDownload(payload)).resolves.toBeUndefined();
    expect(click).not.toHaveBeenCalled();
  });

  test("installed iOS app: a refused share (tap too long ago) falls back to the anchor", async () => {
    const click = stubAnchor();
    iosStandalone(async () => {
      throw new DOMException("no gesture", "NotAllowedError");
    });
    await triggerDownload(payload);
    expect(click).toHaveBeenCalledTimes(1);
  });

  test("everywhere else: plain anchor download", async () => {
    const click = stubAnchor();
    stubDisplayMode(false);
    stubNavigator({ userAgent: ANDROID_CHROME, share: vi.fn(), canShare: () => true });
    await triggerDownload(payload);
    expect(click).toHaveBeenCalledTimes(1);
  });
});
