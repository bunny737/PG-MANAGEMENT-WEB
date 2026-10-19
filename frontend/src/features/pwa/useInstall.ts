"use client";

import { useSyncExternalStore } from "react";
import { getInstallState, promptInstall, subscribeInstallState, type InstallState } from "@/lib/pwa";

/** Current install state plus an `install()` that shows the native prompt where one exists.
 * iOS has no prompt: callers show instructions for the "ios" / "ios-in-app" states. */
export function useInstall(): { state: InstallState; install: typeof promptInstall } {
  const state = useSyncExternalStore(subscribeInstallState, getInstallState, () => "unsupported" as const);
  return { state, install: promptInstall };
}
