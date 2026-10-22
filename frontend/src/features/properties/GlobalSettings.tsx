"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import {
  Building,
  ArrowRight,
  ShieldCheck,
  CreditCard,
  Layers,
  Lock,
  Globe
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import { SUPPORTED_LANGUAGES, getLanguageSelectLabel, isActiveLocale } from "@/i18n/config";
import { getCurrentUser, listProperties, updateTenantDefaultLanguage, updateTenantFiscalYearStart } from "@/lib/api";
import { queryKeys } from "@/lib/queryKeys";
import { SubscriptionPanel } from "@/features/subscription/SubscriptionPanel";

const MONTH_NUMBERS = Array.from({ length: 12 }, (_, i) => i + 1);

export function GlobalSettings() {
  const t = useTranslations("settings");
  const tProperties = useTranslations("properties");
  const locale = useLocale();
  const monthLabel = (month: number) =>
    new Intl.DateTimeFormat(locale, { month: "long" }).format(new Date(2000, month - 1, 1));
  const [activeTab, setActiveTab] = useState<"property" | "security" | "subscription">("property");

  const properties = useQuery({ queryKey: queryKeys.properties.list, queryFn: listProperties });
  const [isLoading, setIsLoading] = useState(false);
  const [saveAlert, setSaveAlert] = useState<{ type: string; message: string } | null>(null);

  // Security/Account states — "language" here is the TENANT's default for new
  // accounts, not this browser's own UI locale, so it's seeded from the
  // tenant record, never from the locale cookie.
  const [language, setLanguage] = useState("en");
  // Fiscal year start month (1-12, default April/4) drives analytics' YTD
  // window (D0/D1) — a tenant setting, never hardcoded (invariant 10).
  const [fiscalYearStartMonth, setFiscalYearStartMonth] = useState(4);
  const [isSavingFiscalYear, setIsSavingFiscalYear] = useState(false);
  useEffect(() => {
    getCurrentUser()
      .then((user) => {
        if (user.tenant?.default_language) setLanguage(user.tenant.default_language);
        if (user.tenant?.fiscal_year_start_month) setFiscalYearStartMonth(user.tenant.fiscal_year_start_month);
      })
      .catch(() => {});
  }, []);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordErrors, setPasswordErrors] = useState<Record<string, string>>({});

  const triggerSaveAlert = (type: string, message: string) => {
    setSaveAlert({ type, message });
    setTimeout(() => setSaveAlert(null), 4000);
  };

  const handleSaveSecurity = (e: React.FormEvent) => {
    e.preventDefault();
    const errs: Record<string, string> = {};

    if (!currentPassword) errs.current = t("global.errCurrentRequired");
    if (!newPassword) errs.new = t("global.errNewRequired");
    else if (newPassword.length < 6) errs.new = t("global.errNewMinLength");
    if (newPassword !== confirmPassword) errs.confirm = t("global.errConfirmMatch");

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
      triggerSaveAlert("password", t("global.passwordSavedToast"));
    }, 1500);
  };

  const handleLanguageChange = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    // Tenant default only seeds NEW staff/resident accounts — it must not touch
    // this Owner's own session locale (that's Profile's language_code, saved
    // separately via updateMe). No cookie write, no reload, here.
    try {
      await updateTenantDefaultLanguage(language);
      triggerSaveAlert("language", t("tenantLanguage.successToast"));
    } catch {
      triggerSaveAlert("language", t("tenantLanguage.errorToast"));
    } finally {
      setIsLoading(false);
    }
  };

  const handleFiscalYearChange = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSavingFiscalYear(true);
    try {
      await updateTenantFiscalYearStart(fiscalYearStartMonth);
      triggerSaveAlert("fiscalYear", t("fiscalYear.successToast"));
    } catch {
      triggerSaveAlert("fiscalYear", t("fiscalYear.errorToast"));
    } finally {
      setIsSavingFiscalYear(false);
    }
  };

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      {/* Toast Alert */}
      {saveAlert && (
        <div className="fixed bottom-5 right-5 z-50 flex items-center gap-3 rounded-xl border border-emerald-100 bg-emerald-50 p-4 text-emerald-800 shadow-xl animate-bounce max-w-sm">
          <ShieldCheck className="size-5 text-emerald-600 shrink-0" />
          <div className="text-sm">
            <span className="font-semibold capitalize">{t("global.savedPrefix", { type: saveAlert.type })}</span>
            <p className="text-xs text-emerald-700 mt-0.5">{saveAlert.message}</p>
          </div>
        </div>
      )}

      {/* Header */}
      <div className="flex flex-col gap-4 md:flex-row md:items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-ink md:text-3xl font-display-lg">{t("title")}</h1>
          <p className="mt-1 text-sm text-ink-muted">
            {t("subtitle")}
          </p>
        </div>
      </div>

      {/* Tabs Menu Selection */}
      <div className="flex border-b border-border bg-surface-card rounded-xl p-1 shadow-sm max-w-md">
        {[
          { id: "property", label: t("tabs.property"), icon: Building },
          { id: "security", label: t("tabs.security"), icon: Lock },
          { id: "subscription", label: t("tabs.subscription"), icon: CreditCard },
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
        <div className="animate-fade-in">
          <div className="bg-surface-card border border-border rounded-2xl p-5 shadow-sm space-y-4">
            <div>
              <h2 className="text-sm font-bold uppercase tracking-wider text-ink">{t("global.profilesTitle")}</h2>
              <p className="text-xs text-ink-muted mt-0.5">{t("global.profilesSub")}</p>
            </div>

            {properties.isPending && (
              <p className="text-xs text-ink-muted">{t("global.propertiesLoading")}</p>
            )}

            {properties.isError && (
              <div className="flex items-center justify-between gap-3 rounded-xl border border-border bg-surface-page/35 p-4 text-xs text-ink-muted">
                <span>{t("global.propertiesLoadError")}</span>
                <button
                  type="button"
                  onClick={() => properties.refetch()}
                  className="font-semibold text-accent hover:text-accent-hover cursor-pointer"
                >
                  {t("global.propertiesRetry")}
                </button>
              </div>
            )}

            {properties.isSuccess && properties.data.length === 0 && (
              <div className="rounded-xl border border-dashed border-border p-6 text-center space-y-3">
                <p className="text-xs text-ink-muted">{t("global.propertiesEmpty")}</p>
                <Link
                  href="/properties/add"
                  className="inline-flex rounded-xl bg-accent px-4 py-2 text-xs font-bold text-ink-inverse hover:bg-accent-hover transition-colors"
                >
                  {t("global.propertiesAdd")}
                </Link>
              </div>
            )}

            {properties.isSuccess && properties.data.length > 0 && (
              <div className="space-y-5">
                {properties.data.map((p) => (
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
                        <p className="text-[10px] text-ink-muted">
                          {tProperties(`types.${p.property_type as "pg" | "boys_hostel" | "girls_hostel" | "hostel" | "co_living"}`)} · {p.city}, {p.state}
                        </p>
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
                          <span className="font-semibold text-ink">{t("global.penaltiesPolicy")}</span>
                        </div>
                        <ArrowRight className="size-3.5 text-ink-faint group-hover:text-accent group-hover:translate-x-0.5 transition-all" />
                      </Link>

                      <Link
                        href={`/properties/${p.id}/buildings`}
                        className="flex items-center justify-between p-2.5 rounded-xl border border-border bg-surface-page/35 hover:bg-surface-page hover:border-accent/30 transition-all text-xs group"
                      >
                        <div className="flex items-center gap-2.5">
                          <Layers className="size-4 text-ink-muted group-hover:text-accent transition-colors" />
                          <span className="font-semibold text-ink">{t("global.floorHierarchy")}</span>
                        </div>
                        <ArrowRight className="size-3.5 text-ink-faint group-hover:text-accent group-hover:translate-x-0.5 transition-all" />
                      </Link>
                    </div>
                  </div>
                ))}
              </div>
            )}
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
                {t("tenantLanguage.title")}
              </h2>
              <p className="text-[11px] text-ink-muted leading-relaxed">
                {t("tenantLanguage.subtitle")}
              </p>

              <div className="space-y-1.5">
                <label htmlFor="language" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                  {t("tenantLanguage.label")}
                </label>
                <select
                  id="language"
                  value={language}
                  onChange={(e) => setLanguage(e.target.value)}
                  className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2.5 text-xs text-ink-muted outline-none transition-all focus:ring-4 focus:ring-accent/15 focus:border-accent"
                  disabled={isLoading}
                >
                  {SUPPORTED_LANGUAGES.map((lang) => (
                    <option key={lang.code} value={lang.code} disabled={!isActiveLocale(lang.code)}>
                      {getLanguageSelectLabel(lang)}
                    </option>
                  ))}
                </select>
              </div>

              <button
                type="submit"
                disabled={isLoading}
                className="w-full bg-accent hover:bg-accent-hover text-ink-inverse text-xs font-bold py-2.5 rounded-xl cursor-pointer transition-colors shadow-sm disabled:opacity-50"
              >
                {isLoading ? t("tenantLanguage.saving") : t("tenantLanguage.button")}
              </button>
            </form>

            <form onSubmit={handleFiscalYearChange} className="bg-surface-card border border-border rounded-2xl p-5 shadow-sm space-y-4">
              <h2 className="text-sm font-bold uppercase tracking-wider text-ink border-b border-border pb-2.5 flex items-center gap-1.5">
                <Layers className="size-4.5 text-ink-muted" />
                {t("fiscalYear.title")}
              </h2>
              <p className="text-[11px] text-ink-muted leading-relaxed">
                {t("fiscalYear.subtitle")}
              </p>

              <div className="space-y-1.5">
                <label htmlFor="fiscalYearStartMonth" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                  {t("fiscalYear.label")}
                </label>
                <select
                  id="fiscalYearStartMonth"
                  value={fiscalYearStartMonth}
                  onChange={(e) => setFiscalYearStartMonth(Number(e.target.value))}
                  className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2.5 text-xs text-ink-muted outline-none transition-all focus:ring-4 focus:ring-accent/15 focus:border-accent"
                  disabled={isSavingFiscalYear}
                >
                  {MONTH_NUMBERS.map((month) => (
                    <option key={month} value={month}>
                      {monthLabel(month)}
                    </option>
                  ))}
                </select>
              </div>

              <button
                type="submit"
                disabled={isSavingFiscalYear}
                className="w-full bg-accent hover:bg-accent-hover text-ink-inverse text-xs font-bold py-2.5 rounded-xl cursor-pointer transition-colors shadow-sm disabled:opacity-50"
              >
                {isSavingFiscalYear ? t("fiscalYear.saving") : t("fiscalYear.button")}
              </button>
            </form>
          </div>

          {/* Right Column: Password Change Form */}
          <div className="md:col-span-7 space-y-6">
            <form onSubmit={handleSaveSecurity} className="bg-surface-card border border-border rounded-2xl p-5 shadow-sm space-y-4">
              <h2 className="text-sm font-bold uppercase tracking-wider text-ink border-b border-border pb-2.5 flex items-center gap-1.5">
                <Lock className="size-4.5 text-ink-muted" />
                {t("global.changePassword")}
              </h2>
              <p className="text-[11px] text-ink-muted leading-relaxed">
                {t("global.changePasswordSub")}
              </p>

              {/* Current Password */}
              <div className="space-y-1.5">
                <label htmlFor="current" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                  {t("global.currentPassword")}
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
                  {t("global.newPassword")}
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
                  {t("global.confirmPassword")}
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
                {isLoading ? t("global.savingCredentials") : t("global.updateCredentials")}
              </button>
            </form>
          </div>
        </div>
      )}

      {/* 3. Plan & Subscription Tab */}
      {activeTab === "subscription" && <SubscriptionPanel />}
    </div>
  );
}
