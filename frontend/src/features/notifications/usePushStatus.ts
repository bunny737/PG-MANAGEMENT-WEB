"use client";

import { useSyncExternalStore } from "react";
import { getPushStatus, subscribePushStatus, type PushStatus } from "@/lib/push";

export function usePushStatus(): PushStatus {
  return useSyncExternalStore(subscribePushStatus, getPushStatus, () => "unsupported" as const);
}
