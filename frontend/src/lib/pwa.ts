// Install-state detection for the PWA. Chrome/Edge/Android fire `beforeinstallprompt` once,
// early, so the listener lives at module scope (imported by features/pwa/PwaRegister, which
// the root layout mounts) rather than inside a component that may mount too late. iOS Safari
// has no install event at all: the user must use Share -> Add to Home Screen, so we can only
// detect "this is iOS and not yet installed" and show instructions.

export type InstallState =
  /** Already running as an installed app. */
  | "installed"
  /** The browser offered a native install prompt. */
  | "installable"
  /** iOS Safari / iOS browser that can add to the Home Screen: show instructions. */
  | "ios"
  /** iOS in-app browser (WhatsApp, Instagram, …): cannot install; must open Safari first. */
  | "ios-in-app"
  | "unsupported";

interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

let deferredPrompt: BeforeInstallPromptEvent | null = null;
let installedThisSession = false;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((listener) => listener());

if (typeof window !== "undefined") {
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault(); // keep it for our own button instead of the browser's mini-infobar
    deferredPrompt = event as BeforeInstallPromptEvent;
    emit();
  });
  window.addEventListener("appinstalled", () => {
    deferredPrompt = null;
    installedThisSession = true;
    emit();
  });
}

export function subscribeInstallState(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function isStandalone(): boolean {
  if (typeof window === "undefined") return false;
  const iosStandalone = (navigator as Navigator & { standalone?: boolean }).standalone === true;
  return iosStandalone || window.matchMedia?.("(display-mode: standalone)").matches === true;
}

export function isIos(): boolean {
  if (typeof navigator === "undefined") return false;
  if (/iPad|iPhone|iPod/.test(navigator.userAgent)) return true;
  // iPadOS 13+ reports itself as a Mac; the touch points give it away.
  return navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1;
}

/** Webviews inside other apps omit the `Safari/` UA token (real Safari, Chrome, Firefox and Edge
 * on iOS all include it) and cannot add a site to the Home Screen. */
export function isIosInAppBrowser(): boolean {
  return isIos() && !/Safari\//.test(navigator.userAgent);
}

export function getInstallState(): InstallState {
  if (isStandalone() || installedThisSession) return "installed";
  if (deferredPrompt) return "installable";
  if (isIos()) return isIosInAppBrowser() ? "ios-in-app" : "ios";
  return "unsupported";
}

/** Shows the native install prompt. Resolves to the user's choice, or "unavailable" if the
 * browser never offered one. */
export async function promptInstall(): Promise<"accepted" | "dismissed" | "unavailable"> {
  const event = deferredPrompt;
  if (!event) return "unavailable";
  await event.prompt();
  const { outcome } = await event.userChoice;
  deferredPrompt = null; // a prompt event can only be used once
  emit();
  return outcome;
}
