"use client";

import { useState } from "react";
import { PlayCircle } from "lucide-react";
import { useTranslations } from "next-intl";
import type { TutorialTopic } from "@/lib/api";
import { cn } from "@/lib/utils";
import { VideoPlayerDialog } from "./VideoPlayerDialog";
import { durationMinutes, useTutorialVideos } from "./useTutorialVideos";

/** "Watch how (2 min)" for a topic. Renders nothing until a video exists for it, so screens
 * can place it unconditionally and it appears once a Super Admin adds the video. */
export function WatchVideoButton({ topic, className }: { topic: TutorialTopic; className?: string }) {
  const t = useTranslations("onboarding.video");
  const { byTopic, requestedLanguage } = useTutorialVideos();
  const [open, setOpen] = useState(false);
  const video = byTopic.get(topic);
  if (!video) return null;
  const minutes = durationMinutes(video.duration_seconds);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={cn(
          "inline-flex cursor-pointer items-center gap-1 rounded-lg px-2 py-1 text-xs font-semibold text-accent transition-colors hover:bg-accent-soft max-md:text-m3-primary",
          className
        )}
      >
        <PlayCircle className="size-3.5" aria-hidden />
        {minutes ? t("watchMinutes", { minutes }) : t("watch")}
      </button>
      {open && <VideoPlayerDialog video={video} requestedLanguage={requestedLanguage} onClose={() => setOpen(false)} />}
    </>
  );
}
