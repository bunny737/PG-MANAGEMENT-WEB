"use client";

import { useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useLocale, useTranslations } from "next-intl";
import { formatMoney } from "@/lib/money";
import { formatMonthLabel } from "@/lib/period";
import type { AnalyticsTrend } from "@/lib/api";

// Validated pair (node scripts/validate_palette.js, light mode: all checks
// pass, worst adjacent ΔE 29.9 CVD / 38.5 normal-vision) — slot 1 is this
// app's own --color-accent, so the chart stays on-brand; slot 2 is the
// dataviz skill's default categorical slot 2 (orange), chosen because this
// app has no second categorical token yet.
const SERIES_1 = "#2563EB";
const SERIES_2 = "#eb6834";

interface TrendChartProps {
  trend: AnalyticsTrend;
}

/** D1b trend chart: cash collected vs expenses paid over the trailing
 * months. Redacted series (finance/expenses null) are simply absent —
 * matches the roadmap's "card appears based on what wasn't redacted". */
export function TrendChart({ trend }: TrendChartProps) {
  const t = useTranslations("reports.trend");
  const locale = useLocale();
  const [showTable, setShowTable] = useState(false);

  const hasFinance = trend.series.some((point) => point.finance !== null);
  const hasExpenses = trend.series.some((point) => point.expenses !== null);

  const data = trend.series.map((point) => ({
    month: point.month,
    label: formatMonthLabel(point.month, locale),
    cashCollected: point.finance ? Number(point.finance.cash_collected) : null,
    expensesPaid: point.expenses ? Number(point.expenses.expenses_paid) : null,
  }));

  if (!hasFinance && !hasExpenses) {
    return <p className="text-sm text-ink-muted">{t("noData")}</p>;
  }

  return (
    <div className="space-y-3">
      <div className="h-64 w-full" aria-hidden={showTable}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" vertical={false} />
            <XAxis
              dataKey="label"
              tick={{ fontSize: 11, fill: "var(--color-ink-muted)" }}
              axisLine={{ stroke: "var(--color-border)" }}
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 11, fill: "var(--color-ink-muted)" }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(value: number) => formatMoney(String(value))}
              width={80}
            />
            <Tooltip
              formatter={(value: number) => formatMoney(String(value))}
              contentStyle={{ fontSize: 12, borderRadius: 12, borderColor: "var(--color-border)" }}
            />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            {hasFinance && (
              <Line
                type="monotone"
                dataKey="cashCollected"
                name={t("cashCollected")}
                stroke={SERIES_1}
                strokeWidth={2}
                dot={{ r: 4 }}
                connectNulls
              />
            )}
            {hasExpenses && (
              <Line
                type="monotone"
                dataKey="expensesPaid"
                name={t("expensesPaid")}
                stroke={SERIES_2}
                strokeWidth={2}
                dot={{ r: 4 }}
                connectNulls
              />
            )}
          </LineChart>
        </ResponsiveContainer>
      </div>

      <button
        type="button"
        onClick={() => setShowTable((v) => !v)}
        className="text-xs font-semibold text-accent hover:text-accent-hover cursor-pointer"
      >
        {t("tableView")}
      </button>

      {showTable && (
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full text-left text-xs">
            <thead className="bg-surface-page text-ink-muted">
              <tr>
                <th className="px-3 py-2">{t("title")}</th>
                {hasFinance && <th className="px-3 py-2 text-right">{t("cashCollected")}</th>}
                {hasExpenses && <th className="px-3 py-2 text-right">{t("expensesPaid")}</th>}
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {data.map((row) => (
                <tr key={row.month}>
                  <td className="px-3 py-2 font-medium text-ink">{row.label}</td>
                  {hasFinance && (
                    <td className="px-3 py-2 text-right tabular-nums">
                      {row.cashCollected !== null ? formatMoney(String(row.cashCollected)) : "—"}
                    </td>
                  )}
                  {hasExpenses && (
                    <td className="px-3 py-2 text-right tabular-nums">
                      {row.expensesPaid !== null ? formatMoney(String(row.expensesPaid)) : "—"}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
