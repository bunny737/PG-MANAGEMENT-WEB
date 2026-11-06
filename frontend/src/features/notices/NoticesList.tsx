"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Megaphone, Plus, X } from "lucide-react";
import { EmptyState } from "@/components/shared/EmptyState";
import { PermissionGate } from "@/components/shared/PermissionGate";
import { useActiveProperty } from "@/components/shared/PropertyFilter";
import { SectionError, SectionSkeleton } from "@/components/shared/SectionState";
import {
  ApiError,
  type Announcement,
  type AnnouncementCategory,
  getNotice,
  listNotices,
  type NoticeFilters,
} from "@/lib/api";
import { queryKeys } from "@/lib/queryKeys";
import { cn } from "@/lib/utils";
import { NoticeCard } from "./NoticeCard";
import { NoticeFormSheet } from "./NoticeFormSheet";

type ActivityFilter = "active" | "expired" | "all";

const ACTIVITY_FILTERS: ActivityFilter[] = ["active", "expired", "all"];
const CATEGORIES: AnnouncementCategory[] = ["general", "holiday", "maintenance", "rules", "event"];

export function NoticesList() {
  const t = useTranslations("notices");
  const tCategory = useTranslations("notices.categories");
  const router = useRouter();
  const searchParams = useSearchParams();
  const { propertyId } = useActiveProperty();
  const linkedId = searchParams.get("notice");

  const [activity, setActivity] = useState<ActivityFilter>("active");
  const [category, setCategory] = useState<AnnouncementCategory | "">("");
  const [form, setForm] = useState<Announcement | "new" | null>(null);

  const filters: NoticeFilters = {
    property: propertyId ?? undefined,
    category: category || undefined,
    active: activity === "active" ? "true" : activity === "expired" ? "false" : undefined,
  };

  const { data: notices = [], isLoading, isError, refetch } = useQuery({
    queryKey: queryKeys.notices.list(filters),
    queryFn: () => listNotices(filters),
  });

  // A deep link (from a food holiday's "notice is out of date" warning) is fetched on its own, so it
  // shows even when it has expired or the filters below would hide it.
  const linkedQuery = useQuery({
    queryKey: queryKeys.notices.detail(linkedId ?? ""),
    queryFn: () => getNotice(linkedId as string),
    enabled: !!linkedId,
    retry: false,
  });
  const linked = linkedQuery.data;
  const linkedDeleted = linkedQuery.error instanceof ApiError && linkedQuery.error.status === 404;

  useEffect(() => {
    if (!linked) return;
    document.getElementById(`notice-${linked.id}`)?.scrollIntoView?.({ behavior: "smooth", block: "center" });
  }, [linked]);

  function closeLinked() {
    const params = new URLSearchParams(searchParams);
    params.delete("notice");
    router.replace(`/notices?${params.toString()}`);
  }

  const listed = notices.filter((notice) => notice.id !== linkedId);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-border bg-surface-card p-4">
        <div className="flex gap-2">
          {ACTIVITY_FILTERS.map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => setActivity(value)}
              className={cn(
                "rounded-full px-3 py-1 text-xs font-semibold transition-colors cursor-pointer",
                activity === value ? "bg-ink text-ink-inverse" : "border border-border text-ink-muted"
              )}
            >
              {t(`filters.${value}`)}
            </button>
          ))}
        </div>
        <select
          aria-label={t("filters.category")}
          value={category}
          onChange={(event) => setCategory(event.target.value as AnnouncementCategory | "")}
          className="rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
        >
          <option value="">{t("filters.allCategories")}</option>
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {tCategory(c)}
            </option>
          ))}
        </select>
        <PermissionGate permission="manage_notices">
          <button
            type="button"
            onClick={() => setForm("new")}
            className="ml-auto inline-flex items-center gap-1.5 rounded-xl bg-accent px-3 py-2 text-sm font-semibold text-ink-inverse transition-colors hover:bg-accent-hover cursor-pointer"
          >
            <Plus className="size-4" />
            {t("notice.add")}
          </button>
        </PermissionGate>
      </div>

      {linkedId && (
        <section aria-label={t("linked.title")} className="space-y-2">
          <div className="flex items-center justify-between">
            <h2 className="text-xs font-bold uppercase tracking-wider text-ink-muted">{t("linked.title")}</h2>
            <button
              type="button"
              onClick={closeLinked}
              aria-label={t("linked.close")}
              className="text-ink-faint hover:text-ink cursor-pointer"
            >
              <X className="size-4" />
            </button>
          </div>
          {linkedQuery.isLoading && <SectionSkeleton className="h-28" />}
          {linkedDeleted && <p className="text-sm text-ink-muted">{t("linked.deleted")}</p>}
          {linkedQuery.isError && !linkedDeleted && (
            <SectionError onRetry={() => linkedQuery.refetch()} message={t("notice.errLoadFailed")} />
          )}
          {linked && <NoticeCard notice={linked} onEdit={setForm} onDeleted={closeLinked} highlight />}
        </section>
      )}

      {isLoading && <SectionSkeleton className="h-64" />}
      {isError && <SectionError onRetry={() => refetch()} message={t("notice.errLoadFailed")} />}

      {!isLoading && !isError && listed.length === 0 && !linked && (
        <EmptyState
          icon={Megaphone}
          title={t("notice.emptyTitle")}
          body={t("notice.emptyDesc")}
        />
      )}

      {!isLoading && !isError && listed.length > 0 && (
        <div className="space-y-3">
          {listed.map((notice) => (
            <NoticeCard key={notice.id} notice={notice} onEdit={setForm} />
          ))}
        </div>
      )}

      {form && (
        <NoticeFormSheet
          initial={form === "new" ? undefined : form}
          defaultProperty={propertyId}
          onClose={() => setForm(null)}
        />
      )}
    </div>
  );
}
