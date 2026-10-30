"use client";

import { WifiOff } from "lucide-react";
import { useTranslations } from "next-intl";
import { Dialog } from "@/components/ui/Dialog";
import type { TutorialVideo } from "@/lib/api";
import { FallbackLanguageNote } from "./FallbackLanguageNote";
import { useIsOnline } from "./useTutorialVideos";

interface VideoPlayerDialogProps {
  video: TutorialVideo | null;
  requestedLanguage: string;
  onClose: () => void;
}

/** Plays one tutorial in a privacy-enhanced YouTube embed. The iframe mounts only while the
 * dialog is open, and offline it is replaced by a notice (the PWA never pretends to stream). */
export function VideoPlayerDialog({ video, requestedLanguage, onClose }: VideoPlayerDialogProps) {
  const t = useTranslations("onboarding.video");
  const online = useIsOnline();
  if (!video) return null;

  return (
    <Dialog open onClose={onClose} title={video.title} subtitle={video.description || undefined} className="max-w-3xl">
      <FallbackLanguageNote shown={video.language} requested={requestedLanguage} />
      {online ? (
        <div className="aspect-video w-full overflow-hidden rounded-xl bg-surface-inverse">
          <iframe
            src={`https://www.youtube-nocookie.com/embed/${encodeURIComponent(video.youtube_id)}?rel=0&autoplay=1`}
            title={video.title}
            className="size-full"
            allow="accelerometer; autoplay; encrypted-media; gyroscope; picture-in-picture"
            allowFullScreen
          />
        </div>
      ) : (
        <div role="status" className="flex aspect-video w-full flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border text-center">
          <WifiOff className="size-6 text-ink-faint" aria-hidden />
          <p className="px-6 text-sm text-ink-muted">{t("offline")}</p>
        </div>
      )}
    </Dialog>
  );
}
