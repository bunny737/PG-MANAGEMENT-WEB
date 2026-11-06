"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { AlertTriangle, Pin } from "lucide-react";
import { StatusPill, type Tone } from "@/components/shared/StatusPill";
import { ApiError, type Announcement, type AnnouncementCategory, deleteNotice, markNoticeCurrent } from "@/lib/api";
import { formatDate } from "@/lib/date";
import { afterNoticeChange } from "@/lib/refresh";
import { useSession } from "@/lib/session";
import { cn } from "@/lib/utils";
import { isExpired } from "./helpers";

const CATEGORY_TONE: Record<AnnouncementCategory, Tone> = {
  general: "neutral",
  holiday: "accent",
  maintenance: "warn",
  rules: "neutral",
  event: "good",
};

interface NoticeCardProps {
  notice: Announcement;
  onEdit: (notice: Announcement) => void;
  /** Called after the notice was deleted (the holiday page, for one, needs to react). */
  onDeleted?: () => void;
  /** The deep-linked notice: ringed, so it stands out from the list. */
  highlight?: boolean;
  /** Hide the "View food holiday" link where the holiday is already the page. */
  hideHolidayLink?: boolean;
}

/** One notice on the board, with its "this holiday notice may be out of date" banner. The banner's
 * actions (edit, dismiss) and the card's own edit/delete all need `manage_notices`; without it the
 * banner is just the warning text. */
export function NoticeCard({ notice, onEdit, onDeleted, highlight, hideHolidayLink }: NoticeCardProps) {
  const t = useTranslations("notices");
  const tCategory = useTranslations("notices.categories");
  const { can } = useSession();
  const canManage = can("manage_notices");
  const [error, setError] = useState<string | null>(null);

  const dismissMutation = useMutation({
    mutationFn: () => markNoticeCurrent(notice.id),
    onSuccess: () => afterNoticeChange(),
    onError: (err) => setError(err instanceof ApiError ? err.message : t("notice.errActionFailed")),
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteNotice(notice.id),
    onSuccess: async () => {
      await afterNoticeChange();
      onDeleted?.();
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : t("notice.errActionFailed")),
  });

  function handleDelete() {
    setError(null);
    if (window.confirm(notice.food_holiday ? t("notice.deleteConfirmLinked") : t("notice.deleteConfirm"))) {
      deleteMutation.mutate();
    }
  }

  const expired = isExpired(notice.expires_on);

  return (
    <article
      id={`notice-${notice.id}`}
      className={cn(
        "space-y-3 rounded-2xl border border-border bg-surface-card p-5",
        highlight && "ring-2 ring-accent/40"
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1 space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            {notice.is_pinned && (
              <span className="inline-flex items-center gap-1 text-xs font-semibold text-accent">
                <Pin className="size-3.5" aria-hidden />
                {t("notice.pinned")}
              </span>
            )}
            <StatusPill label={tCategory(notice.category)} tone={CATEGORY_TONE[notice.category]} />
            {expired && notice.expires_on && (
              <StatusPill label={t("notice.expired", { date: formatDate(notice.expires_on) })} tone="warn" />
            )}
          </div>
          <h3 className="text-base font-bold text-ink">{notice.title}</h3>
        </div>
        {canManage && (
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => onEdit(notice)}
              className="text-xs font-semibold text-ink-muted hover:text-ink cursor-pointer"
            >
              {t("notice.edit")}
            </button>
            <button
              type="button"
              onClick={handleDelete}
              disabled={deleteMutation.isPending}
              className="text-xs font-semibold text-status-critical hover:opacity-80 disabled:opacity-60 cursor-pointer"
            >
              {t("notice.delete")}
            </button>
          </div>
        )}
      </div>

      {notice.notice_outdated && (
        <div role="alert" className="space-y-2 rounded-xl border border-status-warn/30 bg-status-warn-soft p-3">
          <p className="flex items-start gap-2 text-sm font-semibold text-status-warn">
            <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
            {t("outdated.title")}
          </p>
          <p className="text-xs text-ink-muted">{t("outdated.body")}</p>
          {canManage && (
            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={() => onEdit(notice)}
                className="text-xs font-semibold text-accent hover:text-accent-hover cursor-pointer"
              >
                {t("outdated.edit")}
              </button>
              <button
                type="button"
                onClick={() => {
                  setError(null);
                  dismissMutation.mutate();
                }}
                disabled={dismissMutation.isPending}
                className="text-xs font-semibold text-ink-muted hover:text-ink disabled:opacity-60 cursor-pointer"
              >
                {t("outdated.dismiss")}
              </button>
            </div>
          )}
        </div>
      )}

      <p className="whitespace-pre-line text-sm text-ink">{notice.body}</p>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-muted">
        <span>{notice.property_name}</span>
        {notice.expires_on && !expired && <span>{t("notice.expires", { date: formatDate(notice.expires_on) })}</span>}
        {notice.created_by_name && <span>{t("notice.postedBy", { name: notice.created_by_name })}</span>}
        {notice.food_holiday && !hideHolidayLink && (
          <Link
            href={`/notices/holidays/${notice.food_holiday}`}
            className="font-semibold text-accent hover:text-accent-hover"
          >
            {t("notice.viewHoliday")}
          </Link>
        )}
      </div>
      {error && (
        <p role="alert" className="text-xs text-status-critical">
          {error}
        </p>
      )}
    </article>
  );
}
