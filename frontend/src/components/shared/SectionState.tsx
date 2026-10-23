"use client";

import { AlertTriangle } from "lucide-react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";

/**
 * The dashboard/reports section-state rule (UX roadmap Phase 1):
 *   - no permission  -> the caller renders nothing at all (never mount this)
 *   - loading         -> a skeleton
 *   - error           -> this component with Retry
 *   - loaded          -> the caller renders its real content
 *
 * This component only covers the loading/error half — callers still decide
 * whether to render anything based on the permission check themselves,
 * since "hidden" means never fetching, not fetching and then hiding.
 */

export function SectionSkeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn("animate-pulse rounded-2xl bg-surface-subtle", className)}
      role="status"
      aria-hidden
    />
  );
}

interface SectionErrorProps {
  onRetry: () => void;
  className?: string;
  /** Override for a more specific message than the generic "Couldn't load this." */
  message?: string;
}

export function SectionError({ onRetry, className, message }: SectionErrorProps) {
  const t = useTranslations("common");
  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-center justify-center gap-2 rounded-2xl border border-border bg-surface-card p-6 text-center",
        className
      )}
    >
      <AlertTriangle className="size-5 text-status-critical" aria-hidden />
      <p className="text-sm text-ink-muted">{message ?? t("sectionState.error")}</p>
      <button
        type="button"
        onClick={onRetry}
        className="rounded-xl border border-border bg-surface-page px-3 py-1.5 text-xs font-semibold text-ink transition-colors hover:bg-surface-subtle cursor-pointer"
      >
        {t("sectionState.retry")}
      </button>
    </div>
  );
}
