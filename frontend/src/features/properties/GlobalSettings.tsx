"use client";

import React, { useState } from "react";
import Link from "next/link";
import { Building, Settings, ShieldAlert, ArrowRight, ShieldCheck, CreditCard, Layers, Home } from "lucide-react";
import { mockProperties } from "./mock-properties";

export function GlobalSettings() {
  const [portalName, setPortalName] = useState("PropManager");
  const [notificationEmail, setNotificationEmail] = useState("admin@propmanager.com");
  const [currency, setCurrency] = useState("USD");
  const [isLoading, setIsLoading] = useState(false);
  const [saveAlert, setSaveAlert] = useState(false);

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setTimeout(() => {
      setIsLoading(false);
      setSaveAlert(true);
      setTimeout(() => setSaveAlert(false), 4000);
    }, 1000);
  };

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      {/* Toast Alert */}
      {saveAlert && (
        <div className="fixed bottom-5 right-5 z-50 flex items-center gap-3 rounded-xl border border-emerald-100 bg-emerald-50 p-4 text-emerald-800 shadow-xl animate-bounce max-w-sm">
          <ShieldCheck className="size-5 text-emerald-600 shrink-0" />
          <div className="text-sm">
            <span className="font-semibold">Portal Configuration Saved</span>
            <p className="text-xs text-emerald-700 mt-0.5">General system settings updated globally.</p>
          </div>
        </div>
      )}

      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-ink md:text-3xl font-display-lg">System Settings</h1>
        <p className="mt-1 text-sm text-ink-muted">
          Configure property-level billing behaviors, penalties, and portal defaults.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-12 items-start">
        {/* Left Column: Properties Configurations list */}
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
                  className="border border-border rounded-2xl p-5 bg-surface-card shadow-sm space-y-4"
                >
                  {/* Property Info header */}
                  <div className="flex items-center gap-3 pb-3 border-b border-border/55">
                    <div className="flex size-10 items-center justify-center rounded-xl bg-surface-page border border-border text-ink-muted shrink-0">
                      <Building className="size-5" />
                    </div>
                    <div>
                      <h4 className="text-sm font-bold text-ink">{p.name}</h4>
                      <p className="text-[10px] text-ink-muted">{p.type} · {p.city}, {p.state}</p>
                    </div>
                  </div>

                  {/* Settings dashboard options */}
                  <div className="grid grid-cols-1 gap-2">
                    {/* 1. Billing settings link */}
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

                    {/* 2. Floor levels setup link */}
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

                    {/* 3. Rooms list link */}
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

        {/* Right Column: General Settings Form */}
        <div className="md:col-span-5 space-y-6">
          <form onSubmit={handleSave} className="bg-surface-card border border-border rounded-2xl p-5 shadow-sm space-y-4">
            <h2 className="text-sm font-bold uppercase tracking-wider text-ink border-b border-border pb-2.5 flex items-center gap-1.5">
              <Settings className="size-4.5 text-ink-muted" />
              General Portal Setup
            </h2>

            {/* Portal Title */}
            <div className="space-y-1.5">
              <label htmlFor="portalName" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                System Brand Title
              </label>
              <input
                id="portalName"
                type="text"
                value={portalName}
                onChange={(e) => setPortalName(e.target.value)}
                className="w-full rounded-xl border border-border bg-surface-card px-4 py-2 text-xs text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent"
                disabled={isLoading}
              />
            </div>

            {/* Notification Email */}
            <div className="space-y-1.5">
              <label htmlFor="email" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                System Notification Email
              </label>
              <input
                id="email"
                type="email"
                value={notificationEmail}
                onChange={(e) => setNotificationEmail(e.target.value)}
                className="w-full rounded-xl border border-border bg-surface-card px-4 py-2 text-xs text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent"
                disabled={isLoading}
              />
            </div>

            {/* Currency Select */}
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

            {/* Info warning */}
            <div className="bg-slate-50 border border-border/80 p-3 rounded-xl flex gap-2 text-[10px] text-ink-muted">
              <ShieldAlert className="size-4.5 text-amber-500 shrink-0 mt-0.5" />
              <p className="leading-relaxed">
                Modifying general configurations requires Owner privileges. Audited log checks are run daily.
              </p>
            </div>

            {/* Submit */}
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
    </div>
  );
}
