"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { Sheet } from "@/components/ui/Sheet";
import {
  ApiError,
  type Announcement,
  type AnnouncementCategory,
  createNotice,
  listProperties,
  type NoticePayload,
  updateNotice,
} from "@/lib/api";
import { afterNoticeChange } from "@/lib/refresh";
import { queryKeys } from "@/lib/queryKeys";
import { isExpired, todayKey } from "./helpers";

const CATEGORIES: AnnouncementCategory[] = ["general", "holiday", "maintenance", "rules", "event"];
const MAX_TITLE = 200;

const INPUT =
  "w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15";
const LABEL = "text-xs font-semibold uppercase tracking-wider text-ink-muted";

interface NoticeFormSheetProps {
  /** The notice being edited; omit to post a new one. */
  initial?: Announcement;
  defaultProperty: string | null;
  onClose: () => void;
}

export function NoticeFormSheet({ initial, defaultProperty, onClose }: NoticeFormSheetProps) {
  const t = useTranslations("notices.form");
  const tCategory = useTranslations("notices.categories");
  const { data: properties = [] } = useQuery({ queryKey: queryKeys.properties.list, queryFn: listProperties });

  const [property, setProperty] = useState(initial?.property ?? defaultProperty ?? "");
  const [title, setTitle] = useState(initial?.title ?? "");
  const [body, setBody] = useState(initial?.body ?? "");
  const [category, setCategory] = useState<AnnouncementCategory>(initial?.category ?? "general");
  const [isPinned, setIsPinned] = useState(initial?.is_pinned ?? false);
  const [expiresOn, setExpiresOn] = useState(initial?.expires_on ?? "");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);

  const today = todayKey();
  const storedExpiry = initial?.expires_on ?? "";
  // The backend accepts any expiry, so "not before today" is only a guard against typos. A notice that
  // already expired keeps its expiry when edited: the guard applies to a date the user picks, never to
  // the one stored (and the date picker's minimum is dropped for it).
  const expiryChanged = expiresOn !== storedExpiry;
  const keepsPastExpiry = !!initial && isExpired(storedExpiry || null, today);
  const textChanged = !!initial && (title.trim() !== initial.title || body.trim() !== initial.body);
  const editsAutoText = !!initial && initial.is_auto_text && !!initial.food_holiday && textChanged;

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const next: Record<string, string> = {};
    if (!initial && !property) next.property = t("propertyRequired");
    if (!title.trim()) next.title = t("titleRequired");
    else if (title.trim().length > MAX_TITLE) next.title = t("titleTooLong", { max: MAX_TITLE });
    if (!body.trim()) next.body = t("bodyRequired");
    if (expiresOn && expiryChanged && expiresOn < today) next.expires_on = t("expiryInPast");
    if (Object.keys(next).length > 0) {
      setErrors(next);
      return;
    }

    let payload: NoticePayload;
    if (initial) {
      // Only what changed: re-sending the unchanged text would make an auto-generated holiday notice
      // look customised, and a stored (possibly past) expiry would be re-validated for nothing.
      payload = {};
      if (title.trim() !== initial.title) payload.title = title.trim();
      if (body.trim() !== initial.body) payload.body = body.trim();
      if (category !== initial.category) payload.category = category;
      if (isPinned !== initial.is_pinned) payload.is_pinned = isPinned;
      if (expiryChanged) payload.expires_on = expiresOn || null;
      if (Object.keys(payload).length === 0) {
        onClose();
        return;
      }
    } else {
      payload = {
        property,
        title: title.trim(),
        body: body.trim(),
        category,
        is_pinned: isPinned,
        expires_on: expiresOn || null,
      };
    }

    setErrors({});
    setSubmitting(true);
    try {
      if (initial) await updateNotice(initial.id, payload);
      else await createNotice(payload);
      await afterNoticeChange();
      onClose();
    } catch (err) {
      if (err instanceof ApiError) {
        const fields: Record<string, string> = {};
        for (const field of ["property", "title", "body", "category", "expires_on"]) {
          const message = err.fieldError(field);
          if (message) fields[field] = message;
        }
        setErrors(Object.keys(fields).length > 0 ? fields : { form: err.message });
      } else {
        setErrors({ form: t("errSaveFailed") });
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Sheet open onClose={onClose} title={initial ? t("editTitle") : t("addTitle")}>
      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        {!initial && (
          <div className="space-y-1.5">
            <label htmlFor="notice-property" className={LABEL}>
              {t("property")}
            </label>
            <select
              id="notice-property"
              value={property}
              onChange={(event) => setProperty(event.target.value)}
              className={INPUT}
            >
              <option value="">—</option>
              {properties.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            {errors.property && <p className="text-xs text-status-critical">{errors.property}</p>}
          </div>
        )}
        <div className="space-y-1.5">
          <label htmlFor="notice-title" className={LABEL}>
            {t("noticeTitle")}
          </label>
          <input
            id="notice-title"
            type="text"
            value={title}
            maxLength={MAX_TITLE}
            onChange={(event) => setTitle(event.target.value)}
            className={INPUT}
          />
          {errors.title && <p className="text-xs text-status-critical">{errors.title}</p>}
        </div>
        <div className="space-y-1.5">
          <label htmlFor="notice-body" className={LABEL}>
            {t("body")}
          </label>
          <textarea
            id="notice-body"
            rows={6}
            value={body}
            onChange={(event) => setBody(event.target.value)}
            className={INPUT}
          />
          {errors.body && <p className="text-xs text-status-critical">{errors.body}</p>}
          {editsAutoText && <p className="text-xs text-ink-muted">{t("autoTextHint")}</p>}
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <label htmlFor="notice-category" className={LABEL}>
              {t("category")}
            </label>
            <select
              id="notice-category"
              value={category}
              onChange={(event) => setCategory(event.target.value as AnnouncementCategory)}
              className={INPUT}
            >
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {tCategory(c)}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1.5">
            <label htmlFor="notice-expires" className={LABEL}>
              {t("expiresOn")}
            </label>
            <input
              id="notice-expires"
              type="date"
              value={expiresOn}
              min={keepsPastExpiry ? undefined : today}
              onChange={(event) => setExpiresOn(event.target.value)}
              className={INPUT}
            />
            {errors.expires_on ? (
              <p className="text-xs text-status-critical">{errors.expires_on}</p>
            ) : (
              <p className="text-xs text-ink-faint">{t("expiresHint")}</p>
            )}
          </div>
        </div>
        <label htmlFor="notice-pinned" className="flex items-start gap-3 cursor-pointer">
          <input
            id="notice-pinned"
            type="checkbox"
            checked={isPinned}
            onChange={(event) => setIsPinned(event.target.checked)}
            className="mt-0.5 size-4 accent-accent"
          />
          <span>
            <span className="block text-sm font-semibold text-ink">{t("pinned")}</span>
            <span className="block text-xs text-ink-muted">{t("pinnedHint")}</span>
          </span>
        </label>
        {errors.form && (
          <p role="alert" className="text-sm text-status-critical">
            {errors.form}
          </p>
        )}
        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded-xl bg-accent py-2.5 text-sm font-semibold text-ink-inverse transition-colors hover:bg-accent-hover disabled:opacity-60 cursor-pointer"
        >
          {submitting ? t("submitting") : initial ? t("save") : t("submit")}
        </button>
      </form>
    </Sheet>
  );
}
