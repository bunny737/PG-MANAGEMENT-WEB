"use client";

import { useMemo, useSyncExternalStore } from "react";
import { onlineManager, useQuery } from "@tanstack/react-query";
import { useLocale } from "next-intl";
import { listTutorialVideos, type TutorialTopic, type TutorialVideo } from "@/lib/api";
import { queryKeys } from "@/lib/queryKeys";

/** The tutorial catalog in `language` (default: the UI locale). The server falls back to
 * English per topic; compare `video.language` with `requestedLanguage` to label that. */
export function useTutorialVideos(language?: string) {
  const locale = useLocale();
  const requestedLanguage = language ?? locale;
  const query = useQuery({
    queryKey: queryKeys.help.videos(requestedLanguage),
    queryFn: () => listTutorialVideos(requestedLanguage),
    staleTime: 5 * 60_000,
  });
  const byTopic = useMemo(
    () => new Map<TutorialTopic, TutorialVideo>((query.data?.videos ?? []).map((video) => [video.topic, video])),
    [query.data]
  );
  return { query, byTopic, requestedLanguage };
}

const subscribe = (callback: () => void) => onlineManager.subscribe(callback);
const getOnline = () => onlineManager.isOnline();

/** TanStack Query's online state, the same signal the OfflineBanner follows. */
export function useIsOnline() {
  return useSyncExternalStore(subscribe, getOnline, () => true);
}

/** Whole minutes for a duration badge; null when the length is unknown. */
export function durationMinutes(seconds: number | null): number | null {
  return seconds ? Math.max(1, Math.round(seconds / 60)) : null;
}
