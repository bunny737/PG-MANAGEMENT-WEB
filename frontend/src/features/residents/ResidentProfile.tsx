"use client";

import React, { useState } from "react";
import Link from "next/link";
import {
  ChevronRight,
  Phone,
  Mail,
  UserCheck,
  ArrowRightLeft,
  LogOut,
  Edit,
  Building,
  CreditCard,
  FileText,
  Wrench,
  CheckCircle,
  FileCheck2,
  Clock,
  Download,
  AlertCircle
} from "lucide-react";
import type { Resident } from "./mock-residents";

export function ResidentProfile({ resident }: { resident: Resident }) {
  const [activeTab, setActiveTab] = useState<"overview" | "financials" | "documents" | "maintenance">("overview");
  const [actionAlert, setActionAlert] = useState<{ type: string; message: string } | null>(null);

  // Get initials for Avatar
  const getInitials = (name: string) => {
    return name
      .split(" ")
      .map((n) => n[0])
      .join("")
      .toUpperCase()
      .slice(0, 2);
  };

  const handleAction = (type: "transfer" | "vacate" | "edit") => {
    let msg = "";
    if (type === "transfer") {
      msg = `Transfer workflow triggered for ${resident.name}. Opening room allocator (FE-06) shortly.`;
    } else if (type === "vacate") {
      msg = `Notice exit checklist wizard initiated for ${resident.name}. Opening exits workflow (FE-10) shortly.`;
    } else {
      msg = `Edit profile configuration panel opened for ${resident.name}.`;
    }
    setActionAlert({ type, message: msg });
    setTimeout(() => setActionAlert(null), 5000);
  };

  return (
    <div className="space-y-6">
      {/* Action Notification Toast */}
      {actionAlert && (
        <div className="fixed bottom-5 right-5 z-50 flex items-center gap-3 rounded-xl border border-blue-100 bg-blue-50 p-4 text-blue-800 shadow-xl animate-bounce max-w-sm">
          {actionAlert.type === "transfer" && <ArrowRightLeft className="size-5 text-blue-600 shrink-0" />}
          {actionAlert.type === "vacate" && <LogOut className="size-5 text-red-600 shrink-0" />}
          {actionAlert.type === "edit" && <Edit className="size-5 text-amber-600 shrink-0" />}
          <div className="text-sm">
            <span className="font-semibold capitalize">{actionAlert.type} Action:</span>
            <p className="text-xs text-blue-700 mt-0.5">{actionAlert.message}</p>
          </div>
        </div>
      )}

      {/* Breadcrumbs & Header Actions */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          {/* Breadcrumbs */}
          <nav aria-label="Breadcrumb" className="flex items-center text-xs text-ink-muted mb-2">
            <ol className="inline-flex items-center space-x-1">
              <li className="inline-flex items-center">
                <Link href="/residents" className="hover:text-accent transition-colors font-medium">
                  Residents
                </Link>
              </li>
              <li className="flex items-center">
                <ChevronRight className="size-3 text-ink-faint mx-1" />
                <span className="text-ink font-semibold">{resident.name}</span>
              </li>
            </ol>
          </nav>

          {/* Profile Name & Status Badge */}
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-bold tracking-tight text-ink md:text-3xl">{resident.name}</h1>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface-card px-3 py-1 text-xs font-semibold text-ink">
              <span className={`size-2 rounded-full ${
                resident.status === "active" 
                  ? "bg-emerald-500" 
                  : resident.status === "notice_period" 
                  ? "bg-red-500" 
                  : "bg-slate-400"
              }`} />
              {resident.status === "active" && "Active"}
              {resident.status === "notice_period" && "Notice Period"}
              {resident.status === "inactive" && "Inactive"}
            </span>
          </div>
        </div>

        {/* Transfer / Vacate Buttons */}
        <div className="flex gap-2.5">
          <button
            onClick={() => handleAction("transfer")}
            className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-accent/40 bg-accent-soft px-4 py-2.5 text-xs font-bold text-accent hover:bg-accent hover:text-ink-inverse active:scale-[0.98] transition-all cursor-pointer"
          >
            <ArrowRightLeft className="size-3.5" />
            Transfer
          </button>
          <button
            onClick={() => handleAction("vacate")}
            className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-status-critical/30 bg-status-critical-soft px-4 py-2.5 text-xs font-bold text-status-critical hover:bg-status-critical hover:text-ink-inverse active:scale-[0.98] transition-all cursor-pointer"
          >
            <LogOut className="size-3.5" />
            Vacate
          </button>
        </div>
      </div>

      {/* Bento Grid layout */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        {/* Left Column: Identity & Contact Card */}
        <div className="lg:col-span-4 space-y-6">
          {/* Identity Card */}
          <div className="rounded-2xl border border-border bg-surface-card p-6 shadow-sm flex flex-col items-center text-center">
            {resident.id === "8492" ? (
              <div className="size-24 rounded-full overflow-hidden border border-border mb-4 shadow-sm bg-surface-page">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  alt={resident.name}
                  src="https://lh3.googleusercontent.com/aida/AP1WRLvmoOE-ZU12UH3hRSPHQnkw6viTKlATfvaxrcRAIBp1Bd5iLRfdQdik_-8zcuuGqQC_p_x-wuBc1zIKRhVKS0FIcU6QUiLwFAhdM826VG9jwL5iWkgiiIZzN9FOlP3f9ay5H0ZIlfGKdas1RYvYQkj_hWXJsbYd28eFLiwro3NRONx4PaCgS29ce4WZSjADA5N8sruQJA_sts90GQeM44IQrPxM0Yr2zbc64nYcWueLXL_PGf1dZxhj62U"
                  className="size-full object-cover"
                />
              </div>
            ) : (
              <div className="size-24 rounded-full border border-border flex items-center justify-center font-bold text-3xl mb-4 bg-slate-100 text-slate-800 shadow-inner">
                {getInitials(resident.name)}
              </div>
            )}

            <h2 className="text-lg font-bold text-ink">{resident.name}</h2>
            <p className="text-xs text-ink-muted mt-0.5">
              Resident ID: <span className="font-mono font-medium">{`RSD-${resident.id}`}</span>
            </p>

            {/* Quick specifications low card */}
            <div className="w-full mt-5 rounded-xl bg-surface-page p-3 border border-border/60 text-left text-xs space-y-2.5">
              <div className="flex justify-between items-center">
                <span className="text-ink-muted">Unit Block / Room</span>
                <span className="font-semibold text-ink">Building {resident.block}, {resident.unit.split("-")[1] || "101"}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-ink-muted">Bed Assignment</span>
                <span className="font-semibold text-ink">Bed A</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-ink-muted">Lease Ends</span>
                <span className="font-semibold text-ink">Oct 31, 2024</span>
              </div>
            </div>

            <button
              onClick={() => handleAction("edit")}
              className="w-full mt-4 inline-flex items-center justify-center gap-1.5 rounded-xl border border-border bg-surface-page py-2 text-xs font-semibold text-ink hover:bg-surface-card transition-colors cursor-pointer"
            >
              <Edit className="size-3.5" />
              Edit Profile
            </button>
          </div>

          {/* Contact Details Card */}
          <div className="rounded-2xl border border-border bg-surface-card p-5 shadow-sm space-y-4">
            <h3 className="text-xs font-bold uppercase tracking-wider text-ink-faint">Contact Information</h3>
            <ul className="space-y-3.5 text-sm">
              <li className="flex items-center gap-3">
                <Mail className="size-4 text-ink-muted shrink-0" />
                <span className="text-ink truncate">{resident.email}</span>
              </li>
              <li className="flex items-center gap-3">
                <Phone className="size-4 text-ink-muted shrink-0" />
                <span className="font-mono text-ink">{resident.phone}</span>
              </li>
              <li className="flex flex-col gap-1.5 pt-3.5 border-t border-border">
                <div className="flex items-center gap-2 text-xs font-bold text-ink-muted">
                  <UserCheck className="size-3.5" />
                  Emergency Contact
                </div>
                <div className="flex flex-col text-xs pl-5.5 space-y-0.5">
                  <span className="font-semibold text-ink">Michael (Guardian)</span>
                  <span className="font-mono text-ink-muted">+1 (555) 837-1192</span>
                </div>
              </li>
            </ul>
          </div>
        </div>

        {/* Right Column: Dynamic Tabs & Details Panel */}
        <div className="lg:col-span-8 space-y-6">
          {/* Custom Navigation Tab List */}
          <div className="flex border-b border-border bg-surface-card rounded-t-xl px-2">
            {[
              { id: "overview", label: "Overview", icon: Building },
              { id: "financials", label: "Financials", icon: CreditCard },
              { id: "documents", label: "Documents", icon: FileText },
              { id: "maintenance", label: "Maintenance", icon: Wrench },
            ].map((tab) => {
              const isActive = activeTab === tab.id;
              const Icon = tab.icon;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id as typeof activeTab)}
                  className={`flex items-center gap-2 border-b-2 px-4 py-3 text-xs font-bold transition-all cursor-pointer whitespace-nowrap ${
                    isActive
                      ? "border-accent text-accent"
                      : "border-transparent text-ink-muted hover:bg-surface-page hover:text-ink"
                  }`}
                >
                  <Icon className="size-4" />
                  {tab.label}
                </button>
              );
            })}
          </div>

          {/* Overview Tab Content */}
          {activeTab === "overview" && (
            <div className="space-y-6 animate-fade-in">
              {/* KPI metrics row */}
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
                {/* Metric 1 */}
                <div className="rounded-xl border border-border bg-surface-card p-4.5 shadow-sm flex flex-col justify-between">
                  <span className="text-xs font-bold text-ink-faint uppercase tracking-wider">Current Balance</span>
                  <span className="text-2xl font-extrabold tracking-tight text-ink mt-2">$0.00</span>
                  <span className="text-xs font-semibold text-emerald-600 mt-2 flex items-center gap-1">
                    <CheckCircle className="size-3.5" /> Paid in full
                  </span>
                </div>

                {/* Metric 2 */}
                <div className="rounded-xl border border-border bg-surface-card p-4.5 shadow-sm flex flex-col justify-between">
                  <span className="text-xs font-bold text-ink-faint uppercase tracking-wider">Open Requests</span>
                  <span className="text-2xl font-extrabold tracking-tight text-ink mt-2">1</span>
                  <span className="text-xs text-ink-muted mt-2">Maintenance tickets</span>
                </div>

                {/* Metric 3 */}
                <div className="rounded-xl border border-border bg-surface-card p-4.5 shadow-sm flex flex-col justify-between col-span-2 sm:col-span-1">
                  <span className="text-xs font-bold text-ink-faint uppercase tracking-wider">Lease Tenure</span>
                  <div className="flex items-baseline gap-1 mt-2">
                    <span className="text-2xl font-extrabold tracking-tight text-ink">8</span>
                    <span className="text-xs text-ink-muted">months</span>
                  </div>
                  <span className="text-xs text-ink-muted mt-2">Since Jan 2024</span>
                </div>
              </div>

              {/* Recent Activity Timeline card */}
              <div className="rounded-2xl border border-border bg-surface-card p-5 shadow-sm">
                <div className="flex justify-between items-center mb-5">
                  <h3 className="text-sm font-bold uppercase tracking-wider text-ink">Recent Activity</h3>
                  <button className="text-xs font-bold text-accent hover:underline cursor-pointer">
                    View All Activity
                  </button>
                </div>
                {/* Timeline */}
                <div className="relative border-l border-border ml-3 pl-6 flex flex-col gap-6.5 py-1">
                  {/* Timeline Item 1 */}
                  <div className="relative">
                    <span className="absolute -left-[30px] top-1.5 flex size-3 items-center justify-center rounded-full bg-accent ring-4 ring-surface-card">
                      <span className="size-1 rounded-full bg-ink-inverse" />
                    </span>
                    <div className="flex flex-col">
                      <span className="text-sm font-semibold text-ink">Rent Payment Received</span>
                      <span className="text-xs text-ink-muted mt-0.5">Invoice #INV-2024-08 for $850.00</span>
                      <span className="flex items-center gap-1 text-[10px] text-ink-faint font-mono mt-1">
                        <Clock className="size-3" /> Aug 1, 2024 · 09:15 AM
                      </span>
                    </div>
                  </div>

                  {/* Timeline Item 2 */}
                  <div className="relative">
                    <span className="absolute -left-[30px] top-1.5 flex size-3 items-center justify-center rounded-full bg-amber-500 ring-4 ring-surface-card">
                      <span className="size-1 rounded-full bg-ink-inverse" />
                    </span>
                    <div className="flex flex-col">
                      <span className="text-sm font-semibold text-ink">Maintenance Request Created</span>
                      <span className="text-xs text-ink-muted mt-0.5">Issue: Leaking faucet in bathroom</span>
                      <span className="flex items-center gap-1 text-[10px] text-ink-faint font-mono mt-1">
                        <Clock className="size-3" /> Jul 28, 2024 · 02:30 PM
                      </span>
                    </div>
                  </div>

                  {/* Timeline Item 3 */}
                  <div className="relative">
                    <span className="absolute -left-[30px] top-1.5 flex size-3 items-center justify-center rounded-full bg-slate-300 ring-4 ring-surface-card">
                      <span className="size-1 rounded-full bg-ink-inverse" />
                    </span>
                    <div className="flex flex-col">
                      <span className="text-sm font-semibold text-ink">Lease Document Signed</span>
                      <span className="text-xs text-ink-muted mt-0.5">Renewal agreement signed electronically</span>
                      <span className="flex items-center gap-1 text-[10px] text-ink-faint font-mono mt-1">
                        <Clock className="size-3" /> Jul 15, 2024 · 11:45 AM
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Financials Tab Content */}
          {activeTab === "financials" && (
            <div className="rounded-2xl border border-border bg-surface-card p-5 shadow-sm space-y-4 animate-fade-in">
              <h3 className="text-sm font-bold uppercase tracking-wider text-ink border-b border-border pb-3">Lease Invoices</h3>
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse text-xs">
                  <thead>
                    <tr className="text-ink-muted bg-surface-page font-semibold border-b border-border">
                      <th className="px-4 py-2.5">Invoice ID</th>
                      <th className="px-4 py-2.5">Issue Date</th>
                      <th className="px-4 py-2.5">Amount</th>
                      <th className="px-4 py-2.5">Status</th>
                      <th className="px-4 py-2.5 text-right">Download</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border text-ink">
                    <tr className="hover:bg-surface-page/35">
                      <td className="px-4 py-3 font-mono">#INV-2024-08</td>
                      <td className="px-4 py-3">Aug 1, 2024</td>
                      <td className="px-4 py-3 font-semibold">$850.00</td>
                      <td className="px-4 py-3">
                        <span className="inline-flex items-center rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold text-emerald-700 border border-emerald-100">Paid</span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button className="p-1 rounded text-ink-muted hover:text-accent cursor-pointer"><Download className="size-4 inline" /></button>
                      </td>
                    </tr>
                    <tr className="hover:bg-surface-page/35">
                      <td className="px-4 py-3 font-mono">#INV-2024-07</td>
                      <td className="px-4 py-3">Jul 1, 2024</td>
                      <td className="px-4 py-3 font-semibold">$850.00</td>
                      <td className="px-4 py-3">
                        <span className="inline-flex items-center rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold text-emerald-700 border border-emerald-100">Paid</span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button className="p-1 rounded text-ink-muted hover:text-accent cursor-pointer"><Download className="size-4 inline" /></button>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Documents Tab Content */}
          {activeTab === "documents" && (
            <div className="rounded-2xl border border-border bg-surface-card p-5 shadow-sm space-y-4 animate-fade-in">
              <h3 className="text-sm font-bold uppercase tracking-wider text-ink border-b border-border pb-3">Stored Documents</h3>
              <div className="space-y-3">
                {/* Doc 1 */}
                <div className="flex items-center justify-between border border-border rounded-xl p-3.5 hover:bg-surface-page/20 transition-colors">
                  <div className="flex items-center gap-3">
                    <div className="flex size-9 items-center justify-center rounded-lg bg-blue-50 text-blue-600 border border-blue-100">
                      <FileCheck2 className="size-5" />
                    </div>
                    <div>
                      <h4 className="text-xs font-semibold text-ink">Lease_Agreement_Signed.pdf</h4>
                      <p className="text-[10px] text-ink-muted">2.4 MB · Updated Jul 15, 2024</p>
                    </div>
                  </div>
                  <button className="flex items-center justify-center gap-1.5 rounded-lg border border-border bg-surface-page px-3 py-1.5 text-[11px] font-semibold text-ink-muted hover:bg-surface-card hover:text-ink transition-colors cursor-pointer">
                    <Download className="size-3.5" /> Download
                  </button>
                </div>

                {/* Doc 2 */}
                <div className="flex items-center justify-between border border-border rounded-xl p-3.5 hover:bg-surface-page/20 transition-colors">
                  <div className="flex items-center gap-3">
                    <div className="flex size-9 items-center justify-center rounded-lg bg-slate-50 text-slate-600 border border-slate-200">
                      <FileText className="size-5" />
                    </div>
                    <div>
                      <h4 className="text-xs font-semibold text-ink">National_ID_Aadhar.pdf</h4>
                      <p className="text-[10px] text-ink-muted">1.1 MB · Updated Jan 03, 2024</p>
                    </div>
                  </div>
                  <button className="flex items-center justify-center gap-1.5 rounded-lg border border-border bg-surface-page px-3 py-1.5 text-[11px] font-semibold text-ink-muted hover:bg-surface-card hover:text-ink transition-colors cursor-pointer">
                    <Download className="size-3.5" /> Download
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Maintenance Tab Content */}
          {activeTab === "maintenance" && (
            <div className="rounded-2xl border border-border bg-surface-card p-5 shadow-sm space-y-4 animate-fade-in">
              <h3 className="text-sm font-bold uppercase tracking-wider text-ink border-b border-border pb-3">Maintenance Log</h3>
              <div className="border border-border rounded-xl p-4.5 bg-surface-page/10">
                <div className="flex items-start justify-between">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-bold text-ink">Leaking bathroom faucet</span>
                      <span className="inline-flex items-center rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-700 border border-amber-100">
                        Assigned
                      </span>
                    </div>
                    <p className="text-xs text-ink-muted">Water leaking continuously from sink faucet. Assigned to plumber.</p>
                  </div>
                  <span className="text-[10px] text-ink-faint font-mono">Jul 28, 2024</span>
                </div>
                <div className="flex items-center gap-2 mt-4 pt-3.5 border-t border-border/50 text-[11px] text-ink-muted">
                  <AlertCircle className="size-3.5 text-amber-500" />
                  Scheduled service date: Jul 29, 2024
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
