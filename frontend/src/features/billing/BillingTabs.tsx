"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { InvoiceList } from "./InvoiceList";
import { PaymentsList } from "./PaymentsList";
import { CashMovementsList } from "./CashMovementsList";
import { DiscountsTab } from "./DiscountsTab";

const TABS = ["invoices", "payments", "cashMovements", "discounts"] as const;
type Tab = (typeof TABS)[number];

/** The /billing shell (replaces the old /financials mock). The active tab
 * and every list filter live in the URL search params, so a drill-down
 * link from the dashboard, a resident's finance card or the layout's dues
 * banner is just a link to /billing?... — no shared client state needed. */
export function BillingTabs() {
  const t = useTranslations("billing");
  const router = useRouter();
  const searchParams = useSearchParams();
  const activeTab = (searchParams.get("tab") as Tab) ?? "invoices";

  function setTab(tab: Tab) {
    const params = new URLSearchParams(searchParams);
    params.set("tab", tab);
    router.push(`/billing?${params.toString()}`);
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-ink md:text-3xl">{t("title")}</h1>
        <p className="mt-1 text-sm text-ink-muted">{t("subtitle")}</p>
      </div>

      <div className="flex gap-2 overflow-x-auto border-b border-border">
        {TABS.map((tab) => (
          <button
            key={tab}
            type="button"
            onClick={() => setTab(tab)}
            className={cn(
              "shrink-0 border-b-2 px-3 py-2.5 text-sm font-semibold transition-colors cursor-pointer",
              activeTab === tab
                ? "border-accent text-accent"
                : "border-transparent text-ink-muted hover:text-ink"
            )}
          >
            {t(`tabs.${tab}`)}
          </button>
        ))}
      </div>

      {activeTab === "invoices" && <InvoiceList />}
      {activeTab === "payments" && <PaymentsList />}
      {activeTab === "cashMovements" && <CashMovementsList />}
      {activeTab === "discounts" && <DiscountsTab />}
    </div>
  );
}
