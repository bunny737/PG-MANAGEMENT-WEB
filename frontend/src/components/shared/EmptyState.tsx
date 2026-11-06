"use client";

import Link from "next/link";
import type { LucideIcon } from "lucide-react";
import { WatchVideoButton } from "@/features/onboarding/WatchVideoButton";
import type { TutorialTopic } from "@/lib/api";
import { useSession } from "@/lib/session";
import { cn } from "@/lib/utils";

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  body?: string;
  /** The next thing to do. Rendered only when the user holds `permission` (always, if unset). */
  cta?: { label: string; href: string; permission?: string };
  /** A tutorial for this screen (Module 23); the link appears once a video exists. */
  videoTopic?: TutorialTopic;
  className?: string;
}

/** An empty list that says what to do next, instead of only that there is nothing here. */
export function EmptyState({ icon: Icon, title, body, cta, videoTopic, className }: EmptyStateProps) {
  const { can, ready } = useSession();
  const showCta = cta && (!cta.permission || (ready && can(cta.permission)));

  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-border px-6 py-14 text-center max-md:border-m3-outline-variant",
        className
      )}
    >
      <Icon className="size-8 text-ink-faint" aria-hidden />
      <p className="text-sm font-semibold text-ink">{title}</p>
      {body && <p className="max-w-sm text-xs text-ink-muted">{body}</p>}
      {(showCta || videoTopic) && (
        <div className="mt-1 flex flex-wrap items-center justify-center gap-2">
          {showCta && (
            <Link
              href={cta.href}
              className="rounded-xl bg-accent px-4 py-2 text-xs font-semibold text-ink-inverse transition-colors hover:bg-accent-hover max-md:bg-m3-primary"
            >
              {cta.label}
            </Link>
          )}
          {videoTopic && <WatchVideoButton topic={videoTopic} />}
        </div>
      )}
    </div>
  );
}
