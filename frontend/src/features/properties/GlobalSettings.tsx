"use client";

import React, { useState } from "react";
import Link from "next/link";
import {
  Building,
  Settings,
  ShieldAlert,
  ArrowRight,
  ShieldCheck,
  CreditCard,
  Layers,
  Home,
  Lock,
  Globe,
  Award,
  Zap,
  Download
} from "lucide-react";
import { mockProperties } from "./mock-properties";

export function GlobalSettings() {
  const [activeTab, setActiveTab] = useState<"property" | "security" | "subscription">("property");

  // Portal setup states
  const [portalName, setPortalName] = useState("PropManager");
  const [notificationEmail, setNotificationEmail] = useState("admin@propmanager.com");
  const [currency, setCurrency] = useState("USD");
  const [isLoading, setIsLoading] = useState(false);
  const [saveAlert, setSaveAlert] = useState<{ type: string; message: string } | null>(null);

  // Security/Account states
  const [language, setLanguage] = useState("en-US");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordErrors, setPasswordErrors] = useState<Record<string, string>>({});

  const triggerSaveAlert = (type: string, message: string) => {
    setSaveAlert({ type, message });
    setTimeout(() => setSaveAlert(null), 4000);
  };

  const handleSavePortal = (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setTimeout(() => {
      setIsLoading(false);
      triggerSaveAlert("portal", "General portal configurations updated successfully.");
    }, 1000);
  };

  const handleSaveSecurity = (e: React.FormEvent) => {
    e.preventDefault();
    const errs: Record<string, string> = {};

    if (!currentPassword) errs.current = "Current Password is required";
    if (!newPassword) errs.new = "New Password is required";
    else if (newPassword.length < 6) errs.new = "Password must be at least 6 characters";
    if (newPassword !== confirmPassword) errs.confirm = "Passwords do not match";

    if (Object.keys(errs).length > 0) {
      setPasswordErrors(errs);
      return;
    }

    setPasswordErrors({});
    setIsLoading(true);
    setTimeout(() => {
      setIsLoading(false);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      triggerSaveAlert("password", "Security credentials updated successfully.");
    }, 1500);
  };

  const handleLanguageChange = (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setTimeout(() => {
      setIsLoading(false);
      triggerSaveAlert("language", "Language preferences updated successfully.");
    }, 800);
  };

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      {/* Toast Alert */}
      {saveAlert && (
        <div className="fixed bottom-5 right-5 z-50 flex items-center gap-3 rounded-xl border border-emerald-100 bg-emerald-50 p-4 text-emerald-800 shadow-xl animate-bounce max-w-sm">
          <ShieldCheck className="size-5 text-emerald-600 shrink-0" />
          <div className="text-sm">
            <span className="font-semibold capitalize">{saveAlert.type} Saved</span>
            <p className="text-xs text-emerald-700 mt-0.5">{saveAlert.message}</p>
          </div>
        </div>
      )}

      {/* Header */}
      <div className="flex flex-col gap-4 md:flex-row md:items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-ink md:text-3xl font-display-lg">System Settings</h1>
          <p className="mt-1 text-sm text-ink-muted">
            Configure property hierarchies, security policies, language setups, and subscription plans.
          </p>
        </div>
      </div>

      {/* Tabs Menu Selection */}
      <div className="flex border-b border-border bg-surface-card rounded-xl p-1 shadow-sm max-w-md">
        {[
          { id: "property", label: "Property Setup", icon: Building },
          { id: "security", label: "Account & Security", icon: Lock },
          { id: "subscription", label: "Plan & Billing", icon: CreditCard },
        ].map((tab) => {
          const isActive = activeTab === tab.id;
          const Icon = tab.icon;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as typeof activeTab)}
              className={`flex flex-1 items-center justify-center gap-2 rounded-lg py-2 text-xs font-bold transition-all cursor-pointer ${
                isActive
                  ? "bg-accent text-ink-inverse shadow-sm"
                  : "text-ink-muted hover:bg-surface-page hover:text-ink"
              }`}
            >
              <Icon className="size-4" />
              {tab.label}
            </button>
          );
        })}
      </div>

      {/* Dynamic Tab Contents */}

      {/* 1. Property Setup Tab */}
      {activeTab === "property" && (
        <div className="grid grid-cols-1 gap-6 md:grid-cols-12 items-start animate-fade-in">
          {/* Left Column: Property Configuration Profiles */}
          <div className="md:col-span-7 space-y-6">
            <div className="bg-surface-card border border-border rounded-2xl p-5 shadow-sm space-y-4">
              <div>
                <h2 className="text-sm font-bold uppercase tracking-wider text-ink">Property Configuration Profiles</h2>
                <p className="text-xs text-ink-muted mt-0.5">Select settings dashboards to configure setup and billing policies.</p>
              </div>

              <div className="space-y-5">
                {mockProperties.map((p) => (
                  <div
                    key={p.id}
                    className="border border-border rounded-2xl p-5 bg-surface-card shadow-sm space-y-4 hover:shadow-md transition-shadow"
                  >
                    {/* Property header */}
                    <div className="flex items-center gap-3 pb-3 border-b border-border/55">
                      <div className="flex size-10 items-center justify-center rounded-xl bg-surface-page border border-border text-ink-muted shrink-0">
                        <Building className="size-5" />
                      </div>
                      <div>
                        <h4 className="text-sm font-bold text-ink">{p.name}</h4>
                        <p className="text-[10px] text-ink-muted">{p.type} · {p.city}, {p.state}</p>
                      </div>
                    </div>

                    {/* Dashboard links */}
                    <div className="grid grid-cols-1 gap-2">
                      <Link
                        href={`/properties/${p.id}/settings`}
                        className="flex items-center justify-between p-2.5 rounded-xl border border-border bg-surface-page/35 hover:bg-surface-page hover:border-accent/30 transition-all text-xs group"
                      >
                        <div className="flex items-center gap-2.5">
                          <CreditCard className="size-4 text-ink-muted group-hover:text-accent transition-colors" />
                          <span className="font-semibold text-ink">Late Penalties & Billing Policy</span>
                        </div>
                        <ArrowRight className="size-3.5 text-ink-faint group-hover:text-accent group-hover:translate-x-0.5 transition-all" />
                      </Link>

                      <Link
                        href={`/properties/${p.id}/floors`}
                        className="flex items-center justify-between p-2.5 rounded-xl border border-border bg-surface-page/35 hover:bg-surface-page hover:border-accent/30 transition-all text-xs group"
                      >
                        <div className="flex items-center gap-2.5">
                          <Layers className="size-4 text-ink-muted group-hover:text-accent transition-colors" />
                          <span className="font-semibold text-ink">Levels & Floor Hierarchy Setup</span>
                        </div>
                        <ArrowRight className="size-3.5 text-ink-faint group-hover:text-accent group-hover:translate-x-0.5 transition-all" />
                      </Link>

                      <Link
                        href={`/properties/${p.id}/floors/${p.id === "skyline" ? "4" : "1"}/rooms`}
                        className="flex items-center justify-between p-2.5 rounded-xl border border-border bg-surface-page/35 hover:bg-surface-page hover:border-accent/30 transition-all text-xs group"
                      >
                        <div className="flex items-center gap-2.5">
                          <Home className="size-4 text-ink-muted group-hover:text-accent transition-colors" />
                          <span className="font-semibold text-ink">Rooms Portfolio Inventory</span>
                        </div>
                        <ArrowRight className="size-3.5 text-ink-faint group-hover:text-accent group-hover:translate-x-0.5 transition-all" />
                      </Link>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Right Column: General Setup */}
          <div className="md:col-span-5 space-y-6">
            <form onSubmit={handleSavePortal} className="bg-surface-card border border-border rounded-2xl p-5 shadow-sm space-y-4">
              <h2 className="text-sm font-bold uppercase tracking-wider text-ink border-b border-border pb-2.5 flex items-center gap-1.5">
                <Settings className="size-4.5 text-ink-muted" />
                General Portal Setup
              </h2>

              <div className="space-y-1.5">
                <label htmlFor="portalName" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                  System Brand Title
                </label>
                <input
                  id="portalName"
                  type="text"
                  value={portalName}
                  onChange={(e) => setPortalName(e.target.value)}
                  className="w-full rounded-xl border border-border bg-surface-card px-4 py-2.5 text-xs text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent"
                  disabled={isLoading}
                />
              </div>

              <div className="space-y-1.5">
                <label htmlFor="email" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                  System Notification Email
                </label>
                <input
                  id="email"
                  type="email"
                  value={notificationEmail}
                  onChange={(e) => setNotificationEmail(e.target.value)}
                  className="w-full rounded-xl border border-border bg-surface-card px-4 py-2.5 text-xs text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent"
                  disabled={isLoading}
                />
              </div>

              <div className="space-y-1.5">
                <label htmlFor="currency" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                  Base Currency Symbol
                </label>
                <select
                  id="currency"
                  value={currency}
                  onChange={(e) => setCurrency(e.target.value)}
                  className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2.5 text-xs text-ink-muted outline-none transition-all focus:ring-4 focus:ring-accent/15 focus:border-accent"
                  disabled={isLoading}
                >
                  <option value="USD">USD ($) - US Dollar</option>
                  <option value="INR">INR (₹) - Indian Rupee</option>
                  <option value="EUR">EUR (€) - Euro</option>
                </select>
              </div>

              <div className="bg-slate-50 border border-border/80 p-3 rounded-xl flex gap-2 text-[10px] text-ink-muted">
                <ShieldAlert className="size-4.5 text-amber-500 shrink-0 mt-0.5" />
                <p className="leading-relaxed">
                  Modifying general configurations requires Owner privileges. Audited log checks are run daily.
                </p>
              </div>

              <button
                type="submit"
                disabled={isLoading}
                className="w-full bg-accent hover:bg-accent-hover text-ink-inverse text-xs font-bold py-2.5 rounded-xl cursor-pointer transition-colors shadow-sm disabled:opacity-50"
              >
                {isLoading ? "Saving Setup..." : "Save Portal Setup"}
              </button>
            </form>
          </div>
        </div>
      )}

      {/* 2. Account & Security Tab */}
      {activeTab === "security" && (
        <div className="grid grid-cols-1 gap-6 md:grid-cols-12 items-start animate-fade-in">
          {/* Left Column: Language settings */}
          <div className="md:col-span-5 space-y-6">
            <form onSubmit={handleLanguageChange} className="bg-surface-card border border-border rounded-2xl p-5 shadow-sm space-y-4">
              <h2 className="text-sm font-bold uppercase tracking-wider text-ink border-b border-border pb-2.5 flex items-center gap-1.5">
                <Globe className="size-4.5 text-ink-muted" />
                Language Settings
              </h2>
              <p className="text-[11px] text-ink-muted leading-relaxed">
                Choose your localization and regional configuration options for invoice generation and portals.
              </p>

              <div className="space-y-1.5">
                <label htmlFor="language" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                  Default Interface Language
                </label>
                <select
                  id="language"
                  value={language}
                  onChange={(e) => setLanguage(e.target.value)}
                  className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2.5 text-xs text-ink-muted outline-none transition-all focus:ring-4 focus:ring-accent/15 focus:border-accent"
                  disabled={isLoading}
                >
                  <option value="en-US">English (United States)</option>
                  <option value="en-GB">English (United Kingdom)</option>
                  <option value="es-ES">Español (España)</option>
                  <option value="hi-IN">हिन्दी (भारत)</option>
                </select>
              </div>

              <button
                type="submit"
                disabled={isLoading}
                className="w-full bg-accent hover:bg-accent-hover text-ink-inverse text-xs font-bold py-2.5 rounded-xl cursor-pointer transition-colors shadow-sm disabled:opacity-50"
              >
                {isLoading ? "Saving Language..." : "Update Language"}
              </button>
            </form>
          </div>

          {/* Right Column: Password Change Form */}
          <div className="md:col-span-7 space-y-6">
            <form onSubmit={handleSaveSecurity} className="bg-surface-card border border-border rounded-2xl p-5 shadow-sm space-y-4">
              <h2 className="text-sm font-bold uppercase tracking-wider text-ink border-b border-border pb-2.5 flex items-center gap-1.5">
                <Lock className="size-4.5 text-ink-muted" />
                Change Password
              </h2>
              <p className="text-[11px] text-ink-muted leading-relaxed">
                Update your login credentials. Security logs record all password reset timelines.
              </p>

              {/* Current Password */}
              <div className="space-y-1.5">
                <label htmlFor="current" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                  Current Password
                </label>
                <input
                  id="current"
                  type="password"
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  className={`w-full rounded-xl border ${
                    passwordErrors.current ? "border-status-critical" : "border-border"
                  } bg-surface-card px-4 py-2.5 text-xs text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent`}
                  disabled={isLoading}
                />
                {passwordErrors.current && <p className="text-xs text-status-critical">{passwordErrors.current}</p>}
              </div>

              {/* New Password */}
              <div className="space-y-1.5">
                <label htmlFor="new" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                  New Password
                </label>
                <input
                  id="new"
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  className={`w-full rounded-xl border ${
                    passwordErrors.new ? "border-status-critical" : "border-border"
                  } bg-surface-card px-4 py-2.5 text-xs text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent`}
                  disabled={isLoading}
                />
                {passwordErrors.new && <p className="text-xs text-status-critical">{passwordErrors.new}</p>}
              </div>

              {/* Confirm Password */}
              <div className="space-y-1.5">
                <label htmlFor="confirm" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                  Confirm New Password
                </label>
                <input
                  id="confirm"
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  className={`w-full rounded-xl border ${
                    passwordErrors.confirm ? "border-status-critical" : "border-border"
                  } bg-surface-card px-4 py-2.5 text-xs text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent`}
                  disabled={isLoading}
                />
                {passwordErrors.confirm && <p className="text-xs text-status-critical">{passwordErrors.confirm}</p>}
              </div>

              <button
                type="submit"
                disabled={isLoading}
                className="w-full bg-accent hover:bg-accent-hover text-ink-inverse text-xs font-bold py-2.5 rounded-xl cursor-pointer transition-colors shadow-sm disabled:opacity-50"
              >
                {isLoading ? "Saving Credentials..." : "Update Security Credentials"}
              </button>
            </form>
          </div>
        </div>
      )}

      {/* 3. Plan & Subscription Tab */}
      {activeTab === "subscription" && (
        <div className="grid grid-cols-1 gap-6 md:grid-cols-12 items-start animate-fade-in">
          {/* Left Column: Plan summary details */}
          <div className="md:col-span-7 space-y-6">
            {/* Current plan card */}
            <div className="bg-surface-card border border-border rounded-2xl p-5 shadow-sm space-y-4">
              <div className="flex justify-between items-start border-b border-border pb-3">
                <div className="space-y-1">
                  <span className="text-[9px] font-bold text-accent border border-accent/25 bg-accent-soft px-2.5 py-0.5 rounded-full uppercase tracking-wider">
                    Premium SaaS Plan
                  </span>
                  <h3 className="text-lg font-bold text-ink">PropManager Pro</h3>
                </div>
                <div className="text-right">
                  <p className="text-xl font-extrabold text-ink">$49.00</p>
                  <p className="text-[10px] text-ink-muted">per month billing</p>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4 text-xs">
                <div className="space-y-0.5">
                  <span className="text-ink-muted">Payment Method</span>
                  <p className="font-semibold text-ink">Mastercard ending in 4921</p>
                </div>
                <div className="space-y-0.5">
                  <span className="text-ink-muted">Renewal Date</span>
                  <p className="font-semibold text-ink">Oct 1, 2024</p>
                </div>
              </div>

              {/* Usage stats bar */}
              <div className="space-y-1.5 pt-2">
                <div className="flex justify-between text-xs">
                  <span className="text-ink-muted">Active Bed Allocations</span>
                  <span className="font-bold text-ink">348 / 500 Beds used</span>
                </div>
                <div className="h-2 w-full bg-surface-page rounded-full overflow-hidden border border-border">
                  <div className="h-full bg-accent rounded-full" style={{ width: "70%" }} />
                </div>
              </div>

              {/* Upgrade Plan button */}
              <button className="w-full inline-flex items-center justify-center gap-1.5 rounded-xl bg-accent px-4 py-2.5 text-xs font-bold text-ink-inverse hover:bg-accent-hover hover:shadow-lg hover:shadow-blue-500/10 transition-all cursor-pointer">
                <Zap className="size-3.5" /> Upgrade Plan Capacity
              </button>
            </div>

            {/* Invoices List */}
            <div className="bg-surface-card border border-border rounded-2xl p-5 shadow-sm space-y-4">
              <h3 className="text-xs font-bold uppercase tracking-wider text-ink border-b border-border pb-3">Subscription Invoices</h3>
              <div className="overflow-x-auto text-xs">
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr className="bg-surface-page font-semibold text-ink-muted border-b border-border">
                      <th className="px-4 py-2.5">Billing Period</th>
                      <th className="px-4 py-2.5">Invoice #</th>
                      <th className="px-4 py-2.5">Amount</th>
                      <th className="px-4 py-2.5 text-right font-medium">Download</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border text-ink">
                    <tr className="hover:bg-surface-page/35">
                      <td className="px-4 py-3">Aug 1 - Aug 31, 2024</td>
                      <td className="px-4 py-3 font-mono">#INV-SUB-842</td>
                      <td className="px-4 py-3 font-semibold">$49.00</td>
                      <td className="px-4 py-3 text-right">
                        <button className="p-1 rounded text-ink-muted hover:text-accent cursor-pointer"><Download className="size-4 inline" /></button>
                      </td>
                    </tr>
                    <tr className="hover:bg-surface-page/35">
                      <td className="px-4 py-3">Jul 1 - Jul 31, 2024</td>
                      <td className="px-4 py-3 font-mono">#INV-SUB-710</td>
                      <td className="px-4 py-3 font-semibold">$49.00</td>
                      <td className="px-4 py-3 text-right">
                        <button className="p-1 rounded text-ink-muted hover:text-accent cursor-pointer"><Download className="size-4 inline" /></button>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          {/* Right Column: Upgrade Plan lists */}
          <div className="md:col-span-5 space-y-6">
            <div className="bg-surface-card border border-border rounded-2xl p-5 shadow-sm space-y-4">
              <h3 className="text-sm font-bold uppercase tracking-wider text-ink border-b border-border pb-2.5 flex items-center gap-1.5">
                <Award className="size-4.5 text-ink-muted" />
                Available Plans
              </h3>

              <div className="space-y-3.5">
                {/* Plan 1 */}
                <div className="border border-border rounded-xl p-3.5 hover:border-accent/40 transition-colors space-y-2">
                  <div className="flex justify-between items-center">
                    <h4 className="text-xs font-bold text-ink">Starter Plan</h4>
                    <span className="font-mono text-xs font-semibold text-ink">$19/mo</span>
                  </div>
                  <p className="text-[10px] text-ink-muted leading-relaxed">
                    Up to 100 beds, basic tenant registration, and manual billing.
                  </p>
                </div>

                {/* Plan 2 */}
                <div className="border-2 border-accent rounded-xl p-3.5 bg-accent-soft/10 space-y-2 relative">
                  <span className="absolute -top-2.5 right-4 bg-accent text-ink-inverse text-[8px] font-extrabold uppercase px-2 py-0.5 rounded-full tracking-wider shadow-sm">
                    Current Plan
                  </span>
                  <div className="flex justify-between items-center">
                    <h4 className="text-xs font-bold text-ink">Pro Plan</h4>
                    <span className="font-mono text-xs font-semibold text-ink">$49/mo</span>
                  </div>
                  <p className="text-[10px] text-ink-muted leading-relaxed">
                    Up to 500 beds, auto late penalty triggers, and custom tenant contracts.
                  </p>
                </div>

                {/* Plan 3 */}
                <div className="border border-border rounded-xl p-3.5 hover:border-accent/40 transition-colors space-y-2">
                  <div className="flex justify-between items-center">
                    <h4 className="text-xs font-bold text-ink">Enterprise Plan</h4>
                    <span className="font-mono text-xs font-semibold text-ink">$99/mo</span>
                  </div>
                  <p className="text-[10px] text-ink-muted leading-relaxed">
                    Unlimited beds, custom roles & permissions matrix, API webhooks, and 24/7 priority support.
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
