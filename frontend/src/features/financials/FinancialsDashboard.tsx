"use client";

import React, { useState } from "react";
import {
  TrendingUp,
  ArrowUpRight,
  Download,
  FilterX,
  Search,
  AlertTriangle,
  ShieldCheck,
  Undo
} from "lucide-react";
import { useTranslations } from "next-intl";
import { StatusPill, getStatusTone } from "@/components/shared/StatusPill";

interface Invoice {
  id: string;
  residentName: string;
  room: string;
  type: "Rent" | "Deposit" | "Penalty" | "Utility";
  amount: number;
  penaltyAmount?: number;
  status: "paid" | "pending" | "overdue";
  dueDate: string;
  paymentDate?: string;
}

export function FinancialsDashboard() {
  const t = useTranslations("financials");
  const tCommon = useTranslations("common");
  const tStatus = useTranslations("status");

  const [filterStatus, setFilterStatus] = useState<"all" | "paid" | "pending" | "overdue">("all");
  const [searchTerm, setSearchTerm] = useState("");
  const [showWaiverModal, setShowWaiverModal] = useState<string | null>(null); // Invoice ID to waive penalty
  const [waiverNote, setWaiverNote] = useState("");
  const [successToast, setSuccessToast] = useState<string | null>(null);

  // Mock Invoice Database
  const [invoices, setInvoices] = useState<Invoice[]>([
    { id: "INV-2024-0801", residentName: "Eleanor Shellstrop", room: "102-A", type: "Rent", amount: 850.00, status: "paid", dueDate: "08/05/2024", paymentDate: "08/01/2024" },
    { id: "INV-2024-0802", residentName: "Alex Smith", room: "402-A", type: "Rent", amount: 850.00, status: "paid", dueDate: "08/05/2024", paymentDate: "08/03/2024" },
    { id: "INV-2024-0803", residentName: "Maria Johnson", room: "204-B", type: "Rent", amount: 650.00, status: "paid", dueDate: "08/05/2024", paymentDate: "08/04/2024" },
    { id: "INV-2024-0804", residentName: "Karan S.", room: "104-C", type: "Rent", amount: 600.00, penaltyAmount: 30.00, status: "overdue", dueDate: "07/05/2024" },
    { id: "INV-2024-0805", residentName: "Rohan Sharma", room: "204-A", type: "Deposit", amount: 300.00, status: "paid", dueDate: "08/01/2024", paymentDate: "07/28/2024" },
    { id: "INV-2024-0806", residentName: "Priya Patel", room: "104-A", type: "Rent", amount: 600.00, status: "pending", dueDate: "08/10/2024" },
    { id: "INV-2024-0807", residentName: "Alex Johnson", room: "1201-A", type: "Rent", amount: 1200.00, penaltyAmount: 50.00, status: "overdue", dueDate: "07/05/2024" }
  ]);

  const handleWaivePenalty = (invoiceId: string) => {
    setShowWaiverModal(invoiceId);
  };

  const submitWaiver = (e: React.FormEvent) => {
    e.preventDefault();
    if (!waiverNote.trim()) {
      alert(t("modal.errNoteRequired"));
      return;
    }

    setInvoices(invoices.map(inv => {
      if (inv.id === showWaiverModal) {
        return {
          ...inv,
          penaltyAmount: undefined,
          status: inv.status === "overdue" ? "pending" : inv.status
        };
      }
      return inv;
    }));

    const selectedInv = invoices.find(inv => inv.id === showWaiverModal);
    setSuccessToast(t("modal.toastBody", { name: selectedInv?.residentName || "", note: waiverNote }));
    setShowWaiverModal(null);
    setWaiverNote("");
    setTimeout(() => setSuccessToast(null), 5000);
  };

  const filteredInvoices = invoices.filter(inv => {
    const matchesSearch =
      inv.residentName.toLowerCase().includes(searchTerm.toLowerCase()) ||
      inv.id.toLowerCase().includes(searchTerm.toLowerCase()) ||
      inv.room.toLowerCase().includes(searchTerm.toLowerCase());

    const matchesStatus = filterStatus === "all" ? true : inv.status === filterStatus;

    return matchesSearch && matchesStatus;
  });

  // Financial statistics calculations
  const totalRevenue = invoices.reduce((acc, curr) => {
    if (curr.status === "paid") return acc + curr.amount;
    return acc;
  }, 0);

  const pendingAmount = invoices.reduce((acc, curr) => {
    if (curr.status === "pending") return acc + curr.amount;
    return acc;
  }, 0);

  const overdueAmount = invoices.reduce((acc, curr) => {
    if (curr.status === "overdue") return acc + curr.amount + (curr.penaltyAmount || 0);
    return acc;
  }, 0);

  return (
    <div className="space-y-6">
      {/* Toast Alert */}
      {successToast && (
        <div className="fixed bottom-5 right-5 z-50 flex items-center gap-3 rounded-xl border border-emerald-100 bg-emerald-50 p-4 text-emerald-800 shadow-xl animate-bounce max-w-sm">
          <ShieldCheck className="size-5 text-emerald-600 shrink-0" />
          <div className="text-sm">
            <span className="font-semibold">{t("modal.toastTitle")}</span>
            <p className="text-xs text-emerald-700 mt-0.5 leading-relaxed">{successToast}</p>
          </div>
        </div>
      )}

      {/* Penalty Waiver Modal Dialog */}
      {showWaiverModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-6 bg-on-surface/40 backdrop-blur-sm transition-opacity duration-300">
          <form onSubmit={submitWaiver} className="bg-surface-card p-6 rounded-2xl max-w-md w-full shadow-2xl border border-border space-y-4">
            <h3 className="text-base font-bold text-ink flex items-center gap-1.5">
              <Undo className="size-4.5 text-accent" />
              {t("modal.title")}
            </h3>
            <p className="text-xs text-ink-muted leading-relaxed">
              {t("modal.sub", { id: showWaiverModal })}
            </p>

            <div className="space-y-1.5">
              <label htmlFor="waiverNote" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                {t("modal.labelNote")} <span className="text-status-critical">*</span>
              </label>
              <textarea
                id="waiverNote"
                rows={3}
                placeholder={t("modal.placeholderNote")}
                value={waiverNote}
                onChange={(e) => setWaiverNote(e.target.value)}
                className="w-full rounded-xl border border-border bg-surface-card px-4 py-2.5 text-xs text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent"
                required
              />
            </div>

            <div className="flex justify-end gap-2.5 pt-2">
              <button
                type="button"
                onClick={() => {
                  setShowWaiverModal(null);
                  setWaiverNote("");
                }}
                className="rounded-xl border border-border bg-surface-page px-4 py-2 text-xs font-bold text-ink hover:bg-surface-card transition-colors cursor-pointer"
              >
                {t("modal.cancel")}
              </button>
              <button
                type="submit"
                className="rounded-xl bg-accent px-4 py-2 text-xs font-bold text-ink-inverse hover:bg-accent-hover transition-colors cursor-pointer"
              >
                {t("modal.confirm")}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-ink md:text-3xl font-display-lg">{t("title")}</h1>
        <p className="mt-1 text-sm text-ink-muted">
          {t("subtitle")}
        </p>
      </div>

      {/* KPI Cards Row */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {/* Metric 1: Total Revenue */}
        <div className="rounded-2xl border border-border bg-surface-card p-5 shadow-sm space-y-3 flex flex-col justify-between">
          <span className="text-xs font-bold text-ink-faint uppercase tracking-wider">{t("kpi.receivedRevenue")}</span>
          <h3 className="text-2xl font-extrabold tracking-tight text-ink">{tCommon("labels.rupeeSymbol")}{totalRevenue.toLocaleString("en-IN")}</h3>
          <span className="text-[10px] text-emerald-600 font-semibold flex items-center gap-0.5">
            <ArrowUpRight className="size-3.5" /> {t("kpi.vsLastMonth")}
          </span>
        </div>

        {/* Metric 2: Pending Invoices */}
        <div className="rounded-2xl border border-border bg-surface-card p-5 shadow-sm space-y-3 flex flex-col justify-between">
          <span className="text-xs font-bold text-ink-faint uppercase tracking-wider">{t("kpi.pendingReceivables")}</span>
          <h3 className="text-2xl font-extrabold tracking-tight text-ink">{tCommon("labels.rupeeSymbol")}{pendingAmount.toLocaleString("en-IN")}</h3>
          <span className="text-[10px] text-ink-muted">{t("kpi.dueBy10th")}</span>
        </div>

        {/* Metric 3: Overdue + Penalty */}
        <div className="rounded-2xl border border-border bg-surface-card p-5 shadow-sm space-y-3 flex flex-col justify-between">
          <span className="text-xs font-bold text-ink-faint uppercase tracking-wider">{t("kpi.overdueBalances")}</span>
          <h3 className="text-2xl font-extrabold tracking-tight text-ink text-status-critical">{tCommon("labels.rupeeSymbol")}{overdueAmount.toLocaleString("en-IN")}</h3>
          <span className="text-[10px] text-status-critical font-semibold flex items-center gap-0.5">
            <AlertTriangle className="size-3.5" /> {t("kpi.includesPenalties")}
          </span>
        </div>

        {/* Metric 4: Collections Rate */}
        <div className="rounded-2xl border border-border bg-surface-card p-5 shadow-sm space-y-3 flex flex-col justify-between">
          <span className="text-xs font-bold text-ink-faint uppercase tracking-wider">{t("kpi.collectionsRate")}</span>
          <h3 className="text-2xl font-extrabold tracking-tight text-ink">95.8%</h3>
          <div className="h-1.5 w-full bg-surface-page rounded-full overflow-hidden border border-border">
            <div className="h-full bg-accent rounded-full" style={{ width: "95.8%" }} />
          </div>
        </div>
      </div>

      {/* Main Section Grid */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12 items-start">
        {/* Left: Collections Chart Card (8 cols) */}
        <div className="lg:col-span-8 bg-surface-card border border-border rounded-2xl p-5 shadow-sm space-y-4">
          <div className="flex justify-between items-center pb-2 border-b border-border/55">
            <h3 className="text-sm font-bold uppercase tracking-wider text-ink flex items-center gap-1.5">
              <TrendingUp className="size-4.5 text-accent animate-pulse" />
              {t("chart.title")}
            </h3>
            <span className="text-[10px] font-bold text-ink-muted">{t("chart.year")}</span>
          </div>

          {/* Simple, gorgeous HTML/CSS bar chart */}
          <div className="h-48 w-full pt-4 flex items-end justify-around gap-2 text-center text-[10px] text-ink-muted font-bold">
            {[
              { label: "Jan", val: 70 },
              { label: "Feb", val: 78 },
              { label: "Mar", val: 82 },
              { label: "Apr", val: 88 },
              { label: "May", val: 92 },
              { label: "Jun", val: 94 },
              { label: "Jul", val: 91 },
              { label: "Aug", val: 95.8 }
            ].map((bar, idx) => (
              <div key={idx} className="flex-grow flex flex-col items-center gap-2 max-w-[44px]">
                <span className="font-mono text-[9px] text-ink-faint">{bar.val}%</span>
                <div className="w-full bg-surface-page border border-border/80 rounded-t-lg h-28 relative flex items-end overflow-hidden">
                  <div
                    className="w-full bg-accent rounded-t group-hover:bg-accent-hover transition-colors"
                    style={{ height: `${bar.val}%` }}
                  />
                </div>
                <span>{bar.label}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Right: Quick Billing Info (4 cols) */}
        <div className="lg:col-span-4 bg-surface-inverse text-ink-inverse rounded-2xl p-5 shadow-md space-y-4">
          <h3 className="text-xs font-bold uppercase tracking-wider text-white/50 border-b border-white/10 pb-2.5 flex items-center gap-1.5">
            <ShieldCheck className="size-4.5 text-accent" />
            {t("ops.title")}
          </h3>
          <div className="space-y-3.5 text-xs text-white/80 leading-relaxed">
            <p>{t("ops.desc1")}</p>
            <p>{t("ops.desc2")}</p>
            <div className="pt-2">
              <span className="font-bold text-white uppercase tracking-wider text-[9px] block mb-1">{t("ops.quickAction")}</span>
              <button className="w-full bg-white text-slate-900 font-bold py-2 rounded-xl text-xs hover:bg-slate-100 transition-colors">
                {t("ops.regenerateInvoices")}
              </button>
            </div>
          </div>
        </div>

        {/* Bottom: Transaction Invoices List */}
        <div className="lg:col-span-12 bg-surface-card border border-border rounded-2xl overflow-hidden shadow-sm space-y-4 p-5">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center justify-between">
            <div>
              <h3 className="text-xs font-bold uppercase tracking-wider text-ink-faint">{t("log.title")}</h3>
              <p className="text-[10px] text-ink-muted mt-0.5">{t("log.subtitle")}</p>
            </div>

            {/* Filters */}
            <div className="flex flex-wrap gap-2 items-center">
              {[
                { id: "all", label: t("log.all") },
                { id: "paid", label: t("log.paid") },
                { id: "pending", label: t("log.pending") },
                { id: "overdue", label: t("log.overdue") },
              ].map((tab) => {
                const isActive = filterStatus === tab.id;
                return (
                  <button
                    key={tab.id}
                    onClick={() => setFilterStatus(tab.id as typeof filterStatus)}
                    className={`rounded-full px-3.5 py-1 text-[10px] font-bold uppercase tracking-wide transition-all cursor-pointer ${
                      isActive
                        ? "bg-surface-inverse text-ink-inverse shadow-sm"
                        : "bg-surface-page text-ink-muted border border-border hover:bg-surface-card hover:text-ink"
                    }`}
                  >
                    {tab.label}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Search bar */}
          <div className="relative max-w-xs">
            <span className="absolute inset-y-0 left-0 flex items-center pl-3.5 text-ink-faint">
              <Search className="size-4" />
            </span>
            <input
              type="text"
              placeholder={t("log.searchPlaceholder")}
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full rounded-xl border border-border bg-surface-card py-2 pl-9 pr-4 text-xs text-ink outline-none transition-all focus:ring-4 focus:ring-accent/15 focus:border-accent"
            />
          </div>

          {/* Table */}
          {filteredInvoices.length > 0 ? (
            <div className="overflow-x-auto text-xs pt-2">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-surface-page font-semibold text-ink-muted border-b border-border">
                    <th className="px-4 py-2.5">{t("log.tableInvoice")}</th>
                    <th className="px-4 py-2.5">{t("log.tableResident")}</th>
                    <th className="px-4 py-2.5">{t("log.tableRoom")}</th>
                    <th className="px-4 py-2.5">{t("log.tableType")}</th>
                    <th className="px-4 py-2.5">{t("log.tableAmount")}</th>
                    <th className="px-4 py-2.5">{t("log.tableDueDate")}</th>
                    <th className="px-4 py-2.5">{t("log.tableStatus")}</th>
                    <th className="px-4 py-2.5 text-right">{t("log.tableActions")}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border text-ink">
                  {filteredInvoices.map((inv) => (
                    <tr key={inv.id} className="hover:bg-surface-page/35">
                      <td className="px-4 py-3 font-mono font-medium">{inv.id}</td>
                      <td className="px-4 py-3 font-semibold">{inv.residentName}</td>
                      <td className="px-4 py-3 font-mono text-ink-muted">{inv.room}</td>
                      <td className="px-4 py-3 text-ink-muted">{t(`types.${inv.type}`)}</td>
                      <td className="px-4 py-3 font-mono">
                        <span className="font-semibold">{tCommon("labels.rupeeSymbol")}{inv.amount.toLocaleString("en-IN")}</span>
                        {inv.penaltyAmount && (
                          <span className="text-[10px] text-status-critical ml-1 font-bold">
                            {t("log.penaltyTag", { amount: inv.penaltyAmount.toLocaleString("en-IN") })}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-ink-muted">{inv.dueDate}</td>
                      <td className="px-4 py-3">
                        <StatusPill
                          label={tStatus(inv.status as "draft" | "issued" | "paid" | "partially_paid" | "void") ?? inv.status}
                          tone={getStatusTone(inv.status)}
                        />
                      </td>
                      <td className="px-4 py-3 text-right space-x-2">
                        {inv.status === "overdue" && inv.penaltyAmount && (
                          <button
                            onClick={() => handleWaivePenalty(inv.id)}
                            className="text-[10px] font-bold text-accent border border-accent/20 bg-accent-soft hover:bg-accent hover:text-white px-2.5 py-1 rounded transition-colors cursor-pointer"
                          >
                            {t("log.waivePenalty")}
                          </button>
                        )}
                        <button className="p-1 rounded text-ink-muted hover:text-accent transition-colors cursor-pointer">
                          <Download className="size-4 inline" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center text-center p-8 space-y-4 bg-surface-card">
              <div className="flex size-11 items-center justify-center rounded-full bg-surface-page text-ink-muted border border-border">
                <FilterX className="size-5 text-ink-faint animate-pulse" />
              </div>
              <div className="space-y-1">
                <h3 className="text-xs font-bold text-ink">{t("log.emptyTitle")}</h3>
                <p className="text-[10px] text-ink-muted">{t("log.emptyDesc")}</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
