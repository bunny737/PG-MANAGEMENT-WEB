"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { Archive } from "lucide-react";
import { ApiError, archiveExpenseCategory, createExpenseCategory, type ExpenseCategory } from "@/lib/api";
import { Dialog } from "@/components/ui/Dialog";
import { queryKeys } from "@/lib/queryKeys";

export function CategoryManagerDialog({
  categories,
  onClose,
}: {
  categories: ExpenseCategory[];
  onClose: () => void;
}) {
  const t = useTranslations("expenses.categoryManager");
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: queryKeys.expenses.categories });

  const addMutation = useMutation({
    mutationFn: (value: string) => createExpenseCategory(value),
    onSuccess: () => {
      setName("");
      invalidate();
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  });

  const archiveMutation = useMutation({
    mutationFn: (category: ExpenseCategory) => archiveExpenseCategory(category.id),
    onSuccess: invalidate,
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  });

  return (
    <Dialog open onClose={onClose} title={t("title")}>
      <div className="space-y-4">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (name.trim()) addMutation.mutate(name.trim());
          }}
          className="flex gap-2"
        >
          <input
            type="text"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder={t("addPlaceholder")}
            className="flex-1 rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
          />
          <button
            type="submit"
            disabled={addMutation.isPending}
            className="rounded-xl bg-accent px-4 py-2 text-sm font-semibold text-ink-inverse hover:bg-accent-hover disabled:opacity-60 cursor-pointer"
          >
            {t("add")}
          </button>
        </form>
        {error && <p className="text-sm text-status-critical">{error}</p>}
        <div className="max-h-80 space-y-1 overflow-y-auto">
          {categories.map((category) => (
            <div key={category.id} className="flex items-center justify-between rounded-xl px-3 py-2 text-sm hover:bg-surface-page">
              <div className="flex items-center gap-2">
                <span className={category.is_archived ? "text-ink-faint line-through" : "text-ink"}>
                  {category.label}
                </span>
                {category.is_system && (
                  <span className="rounded-full bg-surface-subtle px-2 py-0.5 text-[10px] font-semibold text-ink-muted">
                    {t("systemBadge")}
                  </span>
                )}
                {category.is_archived && (
                  <span className="rounded-full bg-surface-subtle px-2 py-0.5 text-[10px] font-semibold text-ink-muted">
                    {t("archivedBadge")}
                  </span>
                )}
              </div>
              {!category.is_system && !category.is_archived && (
                <button
                  type="button"
                  onClick={() => archiveMutation.mutate(category)}
                  className="text-ink-faint hover:text-status-critical cursor-pointer"
                  title={t("archive")}
                >
                  <Archive className="size-3.5" />
                </button>
              )}
            </div>
          ))}
        </div>
      </div>
    </Dialog>
  );
}
