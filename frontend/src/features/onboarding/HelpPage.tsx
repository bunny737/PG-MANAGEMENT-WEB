"use client";

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import { LifeBuoy, ListChecks, PlayCircle } from "lucide-react";
import { SectionError, SectionSkeleton } from "@/components/shared/SectionState";
import { LOCALES } from "@/i18n/config";
import { getOnboardingChecklist, restoreOnboarding, type TutorialVideo } from "@/lib/api";
import { queryKeys } from "@/lib/queryKeys";
import { afterOnboardingDismissChange } from "@/lib/refresh";
import { useActiveProperty } from "@/components/shared/PropertyFilter";
import { FallbackLanguageNote } from "./FallbackLanguageNote";
import { VideoPlayerDialog } from "./VideoPlayerDialog";
import { durationMinutes, useTutorialVideos } from "./useTutorialVideos";

/** Languages the picker offers: every language that has videos (from the server, so a Hindi video is
 * selectable before the Hindi UI goes live), plus English and the UI's own language. */
export function videoLanguageOptions(available: readonly string[], uiLocale: string) {
  const wanted = new Set([...available, "en", uiLocale]);
  return LOCALES.filter((option) => wanted.has(option.code));
}

export function HelpPage() {
  const t = useTranslations("onboarding.help");
  const locale = useLocale();
  const [language, setLanguage] = useState(locale);
  const { query, requestedLanguage } = useTutorialVideos(language);
  // The UI-locale catalog (cached for the Watch buttons) supplies the options, so they don't flicker
  // while another language loads.
  const { query: catalog } = useTutorialVideos();
  const languageOptions = videoLanguageOptions(catalog.data?.available_languages ?? [], locale);
  const [playing, setPlaying] = useState<TutorialVideo | null>(null);

  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-6 md:px-8 md:py-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-ink">{t("title")}</h1>
          <p className="mt-1 text-sm text-ink-muted">{t("subtitle")}</p>
        </div>
        <label className="flex items-center gap-2 text-xs font-semibold text-ink-muted">
          {t("language")}
          <select
            value={language}
            onChange={(event) => setLanguage(event.target.value)}
            className="rounded-lg border border-border bg-surface-card px-2 py-1.5 text-sm text-ink"
          >
            {languageOptions.map((option) => (
              <option key={option.code} value={option.code}>
                {option.nativeName}
              </option>
            ))}
          </select>
        </label>
      </div>

      <section className="mt-6" aria-label={t("videosLabel")}>
        {query.isPending && <SectionSkeleton className="h-48" />}
        {query.isError && <SectionError onRetry={() => query.refetch()} />}
        {query.isSuccess && query.data.videos.length === 0 && (
          <div className="flex flex-col items-center gap-2 rounded-2xl border border-dashed border-border py-14 text-center">
            <PlayCircle className="size-8 text-ink-faint" aria-hidden />
            <p className="text-sm text-ink-muted">{t("empty")}</p>
          </div>
        )}
        {query.isSuccess && query.data.videos.length > 0 && (
          <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {query.data.videos.map((video) => (
              <li key={video.topic}>
                <VideoCard video={video} requestedLanguage={requestedLanguage} onPlay={() => setPlaying(video)} />
              </li>
            ))}
          </ul>
        )}
      </section>

      <div className="mt-8 grid grid-cols-1 gap-4 md:grid-cols-2">
        <ChecklistRestore />
        <div className="flex items-start gap-3 rounded-2xl border border-border bg-surface-card p-4">
          <LifeBuoy className="mt-0.5 size-5 shrink-0 text-accent" aria-hidden />
          <div>
            <p className="text-sm font-semibold text-ink">{t("contactTitle")}</p>
            <p className="mt-0.5 text-xs text-ink-muted">{t("contactBody")}</p>
            <a href="/contact" className="mt-2 inline-block text-xs font-semibold text-accent hover:underline">
              {t("contactLink")}
            </a>
          </div>
        </div>
      </div>

      <VideoPlayerDialog video={playing} requestedLanguage={requestedLanguage} onClose={() => setPlaying(null)} />
    </main>
  );
}

function VideoCard({
  video,
  requestedLanguage,
  onPlay,
}: {
  video: TutorialVideo;
  requestedLanguage: string;
  onPlay: () => void;
}) {
  const t = useTranslations("onboarding");
  const minutes = durationMinutes(video.duration_seconds);
  return (
    <button
      type="button"
      onClick={onPlay}
      className="group flex w-full cursor-pointer flex-col overflow-hidden rounded-2xl border border-border bg-surface-card text-left shadow-sm transition-shadow hover:shadow-md"
    >
      <span className="relative block aspect-video w-full bg-surface-inverse">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={`https://i.ytimg.com/vi/${encodeURIComponent(video.youtube_id)}/mqdefault.jpg`}
          alt=""
          loading="lazy"
          className="size-full object-cover opacity-90 transition-opacity group-hover:opacity-100"
        />
        <PlayCircle className="absolute inset-0 m-auto size-12 text-white drop-shadow" aria-hidden />
        {minutes && (
          <span className="absolute right-2 bottom-2 rounded bg-black/70 px-1.5 py-0.5 text-[11px] font-semibold text-white">
            {t("help.minutes", { minutes })}
          </span>
        )}
      </span>
      <span className="flex flex-col gap-1 p-3">
        <span className="text-[11px] font-bold uppercase tracking-wider text-ink-faint">{t(`topics.${video.topic}`)}</span>
        <span className="text-sm font-semibold text-ink">{video.title}</span>
        <FallbackLanguageNote shown={video.language} requested={requestedLanguage} />
      </span>
    </button>
  );
}

/** "Show the getting-started checklist again" — only for a user who hid it. */
function ChecklistRestore() {
  const t = useTranslations("onboarding.help");
  const { propertyId } = useActiveProperty();
  const checklist = useQuery({
    queryKey: queryKeys.onboarding.checklist(propertyId),
    queryFn: () => getOnboardingChecklist(propertyId),
  });
  const restore = useMutation({ mutationFn: restoreOnboarding, onSuccess: () => afterOnboardingDismissChange() });
  if (!checklist.data?.dismissed || checklist.data.status === "no_actions") return null;

  return (
    <div className="flex items-start gap-3 rounded-2xl border border-border bg-surface-card p-4">
      <ListChecks className="mt-0.5 size-5 shrink-0 text-accent" aria-hidden />
      <div>
        <p className="text-sm font-semibold text-ink">{t("checklistTitle")}</p>
        <button
          type="button"
          onClick={() => restore.mutate()}
          disabled={restore.isPending}
          className="mt-2 cursor-pointer text-xs font-semibold text-accent hover:underline disabled:opacity-60"
        >
          {t("showChecklist")}
        </button>
      </div>
    </div>
  );
}
