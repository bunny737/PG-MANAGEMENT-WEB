"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery } from "@tanstack/react-query";
import { CheckCircle2, Circle, PartyPopper, Rocket, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { ProgressBar } from "@/components/shared/ProgressBar";
import { SectionError } from "@/components/shared/SectionState";
import { useActiveProperty } from "@/components/shared/PropertyFilter";
import { dismissOnboarding, getOnboardingChecklist, type OnboardingChecklist, type OnboardingStep } from "@/lib/api";
import { queryKeys } from "@/lib/queryKeys";
import { afterOnboardingDismissChange } from "@/lib/refresh";
import { useSession } from "@/lib/session";
import { cn } from "@/lib/utils";
import { stepHref } from "./routes";
import { WatchVideoButton } from "./WatchVideoButton";

/**
 * The dashboard's Getting started checklist (Module 23). The server decides everything —
 * target property, which steps count, progress, status — and this only renders it:
 *   dismissed or no_actions -> nothing; in_progress -> the checklist; completed -> "All set"
 *   with a Hide button. Nothing here ever dismisses on its own.
 * Loading renders nothing (most dashboards never show the card, so a skeleton would flash).
 */
export function GettingStartedCard() {
  const { user } = useSession();
  const { propertyId } = useActiveProperty();
  // A profile that already says "dismissed" skips the request; restore refreshes the profile.
  const knownDismissed = user?.onboarding_dismissed === true;
  const query = useQuery({
    queryKey: queryKeys.onboarding.checklist(propertyId),
    queryFn: () => getOnboardingChecklist(propertyId),
    enabled: !knownDismissed,
    refetchOnMount: "always",
  });

  if (knownDismissed || query.isPending) return null;
  if (query.isError) return <SectionError onRetry={() => query.refetch()} />;
  const checklist = query.data;
  if (checklist.dismissed || checklist.status === "no_actions") return null;
  return <ChecklistCard checklist={checklist} />;
}

export function ChecklistCard({ checklist }: { checklist: OnboardingChecklist }) {
  const t = useTranslations("onboarding.card");
  const [confirming, setConfirming] = useState(false);
  const dismiss = useMutation({ mutationFn: dismissOnboarding, onSuccess: () => afterOnboardingDismissChange() });
  const name = checklist.target_property?.name;
  const { done, total } = checklist.progress;
  const required = checklist.steps.filter((step) => step.required);
  const optional = checklist.steps.filter((step) => !step.required && step.permitted && !step.done);
  const completed = checklist.status === "completed";

  return (
    <section
      aria-labelledby="getting-started-title"
      className="rounded-2xl border border-border bg-surface-card p-5 shadow-sm max-md:border-m3-outline-variant max-md:bg-m3-surface"
    >
      <div className="flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-accent-soft text-accent max-md:bg-m3-primary-container max-md:text-m3-primary">
          {completed ? <PartyPopper className="size-5" aria-hidden /> : <Rocket className="size-5" aria-hidden />}
        </span>
        <div className="min-w-0 flex-1">
          <h2 id="getting-started-title" className="text-base font-bold text-ink">
            {completed ? t("allSetTitle") : name ? t("title", { name }) : t("titleGeneric")}
          </h2>
          <p className="mt-0.5 text-xs text-ink-muted">
            {completed
              ? name ? t("allSetBody", { name }) : t("allSetBodyGeneric")
              : t("subtitle", { done, total })}
          </p>
        </div>
        {!completed && !confirming && (
          <button
            type="button"
            onClick={() => setConfirming(true)}
            aria-label={t("hide")}
            className="shrink-0 cursor-pointer rounded-lg p-1 text-ink-muted transition-colors hover:text-ink"
          >
            <X className="size-4" aria-hidden />
          </button>
        )}
      </div>

      {!completed && (
        <div className="mt-4">
          <ProgressBar percent={total > 0 ? (done / total) * 100 : 0} label={t("progressLabel")} />
        </div>
      )}

      {confirming && (
        <div role="alertdialog" aria-label={t("hide")} className="mt-4 flex flex-wrap items-center gap-2 rounded-xl bg-surface-subtle p-3 text-sm text-ink">
          <p className="min-w-0 flex-1">{t("hideConfirm")}</p>
          <button type="button" onClick={() => setConfirming(false)} className="cursor-pointer rounded-lg px-3 py-1.5 text-xs font-semibold text-ink-muted hover:text-ink">
            {t("cancel")}
          </button>
          <button
            type="button"
            onClick={() => dismiss.mutate()}
            disabled={dismiss.isPending}
            className="cursor-pointer rounded-lg bg-accent px-3 py-1.5 text-xs font-semibold text-ink-inverse hover:bg-accent-hover disabled:opacity-60 max-md:bg-m3-primary"
          >
            {t("hideYes")}
          </button>
        </div>
      )}

      {!completed && (
        <ol className="mt-4 flex flex-col gap-1">
          {required.map((step) => (
            <StepRow key={step.key} step={step} isNext={step.key === checklist.next_step} />
          ))}
        </ol>
      )}

      {!completed && optional.length > 0 && (
        <div className="mt-3 border-t border-border pt-3">
          <p className="px-2 text-xs font-bold uppercase tracking-wider text-ink-faint">{t("alsoTry")}</p>
          <ul className="mt-1 flex flex-col gap-1">
            {optional.map((step) => (
              <StepRow key={step.key} step={step} isNext={false} />
            ))}
          </ul>
        </div>
      )}

      {completed && (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Link
            href="/help"
            className="rounded-lg border border-border px-3 py-1.5 text-xs font-semibold text-ink transition-colors hover:bg-surface-page"
          >
            {t("openHelp")}
          </Link>
          <button
            type="button"
            onClick={() => dismiss.mutate()}
            disabled={dismiss.isPending}
            className="cursor-pointer rounded-lg bg-accent px-3 py-1.5 text-xs font-semibold text-ink-inverse hover:bg-accent-hover disabled:opacity-60 max-md:bg-m3-primary"
          >
            {t("hideYes")}
          </button>
        </div>
      )}
    </section>
  );
}

function StepRow({ step, isNext }: { step: OnboardingStep; isNext: boolean }) {
  const t = useTranslations("onboarding");
  const href = stepHref(step);
  const open = !step.done && step.permitted && step.blocked_by === null;

  return (
    <li
      className={cn(
        "flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl px-2 py-2",
        isNext && "bg-accent-soft/60 max-md:bg-m3-primary-container/40"
      )}
    >
      {step.done ? (
        <CheckCircle2 className="size-5 shrink-0 text-status-good" aria-label={t("card.done")} />
      ) : (
        <Circle className={cn("size-5 shrink-0", open ? "text-accent max-md:text-m3-primary" : "text-ink-faint")} aria-hidden />
      )}
      <span
        className={cn(
          "min-w-0 flex-1 text-sm",
          step.done ? "text-ink-muted line-through decoration-ink-faint" : open ? "font-semibold text-ink" : "text-ink-faint"
        )}
      >
        {t(`steps.${step.key}`)}
      </span>
      {/* A done row offers only the tutorial — no CTA, no "Ask your owner". */}
      {!step.done && !step.permitted && <span className="text-xs text-ink-muted">{t("card.askOwner")}</span>}
      {!step.done && step.permitted && step.blocked_by !== null && (
        <span className="text-xs text-ink-faint">{t("card.after", { step: t(`steps.${step.blocked_by}`) })}</span>
      )}
      <WatchVideoButton topic={step.video_topic} />
      {open && href && (
        <Link
          href={href}
          className={cn(
            "rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors",
            isNext
              ? "bg-accent text-ink-inverse hover:bg-accent-hover max-md:bg-m3-primary"
              : "border border-border text-ink hover:bg-surface-page"
          )}
        >
          {t(`cta.${step.key}`)}
        </Link>
      )}
    </li>
  );
}
