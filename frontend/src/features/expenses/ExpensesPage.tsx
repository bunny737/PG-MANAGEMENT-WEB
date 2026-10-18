"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { Paperclip, Plus, Receipt, Search, Settings, Trash2 } from "lucide-react";
import {
  deleteExpense,
  type Expense,
  type ExpenseFilters,
  getExpenseSummary,
  listExpenseCategories,
  listExpensesFiltered,
} from "@/lib/api";
import { MoneyText } from "@/components/shared/MoneyText";
import { MonthNavigator } from "@/components/shared/MonthNavigator";
import { PermissionGate } from "@/components/shared/PermissionGate";
import { PropertyFilter, useActiveProperty } from "@/components/shared/PropertyFilter";
import { SectionError, SectionSkeleton } from "@/components/shared/SectionState";
import { afterExpenseChange } from "@/lib/refresh";
import { currentMonthKey } from "@/lib/period";
import { queryKeys } from "@/lib/queryKeys";
import { useSession } from "@/lib/session";
import { CategoryManagerDialog } from "./CategoryManagerDialog";
import { ExpenseFormSheet } from "./ExpenseFormSheet";

export function ExpensesPage() {
  const t = useTranslations("expenses");
  const tStatus = useTranslations("status");
  const { can } = useSession();
  const { propertyId } = useActiveProperty();

  const [month, setMonth] = useState(currentMonthKey());
  const [category, setCategory] = useState("");
  const [search, setSearch] = useState("");
  const [showForm, setShowForm] = useState<Expense | "new" | null>(null);
  const [showCategories, setShowCategories] = useState(false);
  const [repeatFrom, setRepeatFrom] = useState<Expense | null>(null);

  // The categories list is fetched first — it also seeds the built-ins.
  const categoriesQuery = useQuery({
    queryKey: queryKeys.expenses.categories,
    queryFn: listExpenseCategories,
  });

  const filters: ExpenseFilters = {
    property: propertyId ?? undefined,
    month,
    category: category || undefined,
    search: search || undefined,
  };

  const { data: expenses = [], isLoading, isError, refetch } = useQuery({
    queryKey: queryKeys.expenses.list(filters),
    queryFn: () => listExpensesFiltered(filters),
  });

  const summaryQuery = useQuery({
    queryKey: queryKeys.expenses.summary({ property: propertyId, month }),
    queryFn: () => getExpenseSummary({ property: propertyId ?? undefined, month }),
  });

  const deleteMutation = useMutation({
    mutationFn: (expense: Expense) => deleteExpense(expense.id),
    onSuccess: async () => {
      await afterExpenseChange();
    },
  });

  function handleDelete(expense: Expense) {
    if (window.confirm(t("deleteConfirmBody"))) deleteMutation.mutate(expense);
  }

  const groupedByDate = useMemo(() => {
    const groups = new Map<string, Expense[]>();
    for (const expense of expenses) {
      const list = groups.get(expense.date) ?? [];
      list.push(expense);
      groups.set(expense.date, list);
    }
    return Array.from(groups.entries()).sort((a, b) => (a[0] < b[0] ? 1 : -1));
  }, [expenses]);

  const canManage = can("manage_expenses");

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-ink">{t("title")}</h1>
          <p className="text-sm text-ink-muted">{t("subtitle")}</p>
        </div>
        <PermissionGate permission="manage_expenses">
          <button
            type="button"
            onClick={() => setShowForm("new")}
            className="inline-flex items-center gap-1.5 rounded-xl bg-accent px-3 py-2 text-sm font-semibold text-ink-inverse transition-colors hover:bg-accent-hover cursor-pointer"
          >
            <Plus className="size-4" />
            {t("add")}
          </button>
        </PermissionGate>
      </div>

      <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-border bg-surface-card p-4">
        <MonthNavigator value={month} onChange={setMonth} />
        <PropertyFilter />
        <div className="relative min-w-[12rem] flex-1">
          <Search className="absolute inset-y-0 left-3 my-auto size-4 text-ink-faint" />
          <input
            type="text"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t("filters.search")}
            className="w-full rounded-xl border border-border bg-surface-card py-2 pl-9 pr-3 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
          />
        </div>
        <PermissionGate permission="manage_expenses">
          <button
            type="button"
            onClick={() => setShowCategories(true)}
            className="inline-flex items-center gap-1.5 rounded-xl border border-border bg-surface-card px-3 py-2 text-xs font-semibold text-ink-muted transition-colors hover:text-ink cursor-pointer"
          >
            <Settings className="size-3.5" />
            {t("manageCategories")}
          </button>
        </PermissionGate>
      </div>

      {/* Category chips, from the summary so they reconcile with the total */}
      {summaryQuery.data && (
        <div className="flex flex-wrap items-center gap-4">
          <div className="rounded-2xl border border-border bg-surface-card px-4 py-2">
            <span className="text-xs text-ink-faint">{t("total")}</span>{" "}
            <MoneyText value={summaryQuery.data.total} className="font-bold text-ink" />
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setCategory("")}
              className={`rounded-full px-3 py-1 text-xs font-semibold transition-colors cursor-pointer ${
                category === "" ? "bg-ink text-ink-inverse" : "border border-border text-ink-muted"
              }`}
            >
              {t("filters.allCategories")}
            </button>
            {summaryQuery.data.by_category.map((row) => (
              <button
                key={row.category}
                type="button"
                onClick={() => setCategory(row.category)}
                className={`rounded-full px-3 py-1 text-xs font-semibold transition-colors cursor-pointer ${
                  category === row.category ? "bg-ink text-ink-inverse" : "border border-border text-ink-muted"
                }`}
              >
                {row.name} · <MoneyText value={row.total} />
              </button>
            ))}
          </div>
        </div>
      )}

      {isLoading && <SectionSkeleton className="h-64" />}
      {isError && <SectionError onRetry={() => refetch()} message={t("errLoadFailed")} />}

      {!isLoading && !isError && expenses.length === 0 && (
        <div className="flex flex-col items-center gap-2 rounded-2xl border border-border bg-surface-card p-12 text-center">
          <Receipt className="size-8 text-ink-faint" />
          <h3 className="text-sm font-bold text-ink">{t("emptyTitle")}</h3>
          <p className="text-xs text-ink-muted">{t("emptyDesc")}</p>
        </div>
      )}

      {!isLoading && !isError && groupedByDate.length > 0 && (
        <div className="space-y-4">
          {groupedByDate.map(([date, rows]) => (
            <div key={date} className="overflow-hidden rounded-2xl border border-border bg-surface-card">
              <div className="border-b border-border bg-surface-page px-5 py-2 text-xs font-bold uppercase tracking-wider text-ink-muted">
                {date}
              </div>
              <div className="divide-y divide-border">
                {rows.map((expense) => (
                  <div key={expense.id} className="flex items-center justify-between gap-3 px-5 py-3 text-sm">
                    <div className="min-w-0 flex-1">
                      <p className="font-semibold text-ink">
                        {expense.category_name}
                        {expense.has_attachment && <Paperclip className="ml-1.5 inline size-3 text-ink-faint" />}
                      </p>
                      <p className="truncate text-xs text-ink-muted">{expense.note || tStatus(expense.payment_mode)}</p>
                    </div>
                    <MoneyText value={expense.amount} className="font-semibold" />
                    <PermissionGate permission="manage_expenses">
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => setRepeatFrom(expense)}
                          className="text-xs font-semibold text-accent hover:text-accent-hover cursor-pointer"
                        >
                          {t("repeat")}
                        </button>
                        <button
                          type="button"
                          onClick={() => setShowForm(expense)}
                          className="text-xs font-semibold text-ink-muted hover:text-ink cursor-pointer"
                        >
                          {t("edit")}
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDelete(expense)}
                          className="text-ink-faint hover:text-status-critical cursor-pointer"
                        >
                          <Trash2 className="size-3.5" />
                        </button>
                      </div>
                    </PermissionGate>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {canManage && showForm && (
        <ExpenseFormSheet
          initial={showForm === "new" ? undefined : showForm}
          defaultProperty={propertyId}
          categories={categoriesQuery.data ?? []}
          onClose={() => setShowForm(null)}
          viewedMonth={month}
          onViewMonth={(newMonth) => {
            setMonth(newMonth);
            setShowForm(null);
          }}
        />
      )}
      {canManage && repeatFrom && (
        <ExpenseFormSheet
          initial={undefined}
          repeatFrom={repeatFrom}
          defaultProperty={propertyId}
          categories={categoriesQuery.data ?? []}
          onClose={() => setRepeatFrom(null)}
          viewedMonth={month}
          onViewMonth={(newMonth) => {
            setMonth(newMonth);
            setRepeatFrom(null);
          }}
        />
      )}
      {showCategories && (
        <CategoryManagerDialog categories={categoriesQuery.data ?? []} onClose={() => setShowCategories(false)} />
      )}
    </div>
  );
}
