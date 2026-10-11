"use client";

import React, { useState, useEffect, useMemo } from "react";
import {
  Search,
  Plus,
  LoaderCircle,
  AlertTriangle,
  X,
  Phone,
  CheckCircle2,
  LogOut,
  UserCheck,
} from "lucide-react";
import { useTranslations } from "next-intl";
import {
  listVisitors,
  createVisitor,
  checkOutVisitor,
  listResidents,
  type Visitor,
  type Resident,
  ApiError,
} from "@/lib/api";
import { StatusPill } from "@/components/shared/StatusPill";

export function VisitorsLog() {
  const t = useTranslations("visitors");
  const tCommon = useTranslations("common");

  const [visitors, setVisitors] = useState<Visitor[]>([]);
  const [residents, setResidents] = useState<Resident[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");

  // Filters
  const [searchTerm, setSearchTerm] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "checked_in" | "checked_out">("all");

  // Modal / Form state
  const [isLoggingNew, setIsLoggingNew] = useState(false);
  const [formResident, setFormResident] = useState("");
  const [formVisitorName, setFormVisitorName] = useState("");
  const [formMobileNumber, setFormMobileNumber] = useState("");
  const [formPurpose, setFormPurpose] = useState("");
  const [formError, setFormError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Check out in-progress ID
  const [checkingOutId, setCheckingOutId] = useState<string | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3500);
  };

  useEffect(() => {
    let cancelled = false;

    Promise.all([listVisitors(), listResidents().catch(() => [])])
      .then(([visitorsData, residentsData]) => {
        if (cancelled) return;
        setVisitors(visitorsData);
        setResidents(residentsData);
        setIsLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : t("errors.loadFailed"));
        setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [t]);

  const handleReload = () => {
    setIsLoading(true);
    setError("");
    Promise.all([listVisitors(), listResidents().catch(() => [])])
      .then(([visitorsData, residentsData]) => {
        setVisitors(visitorsData);
        setResidents(residentsData);
        setIsLoading(false);
      })
      .catch((err) => {
        setError(err instanceof ApiError ? err.message : t("errors.loadFailed"));
        setIsLoading(false);
      });
  };

  // Map resident id to name
  const residentMap = useMemo(() => {
    const map = new Map<string, Resident>();
    residents.forEach((r) => map.set(r.id, r));
    return map;
  }, [residents]);

  const filteredVisitors = useMemo(() => {
    return visitors.filter((v) => {
      const resident = residentMap.get(v.resident);
      const residentName = resident ? `${resident.first_name} ${resident.last_name}`.toLowerCase() : "";
      const matchesSearch =
        v.visitor_name.toLowerCase().includes(searchTerm.toLowerCase()) ||
        v.mobile_number.includes(searchTerm) ||
        v.purpose.toLowerCase().includes(searchTerm.toLowerCase()) ||
        residentName.includes(searchTerm.toLowerCase());

      if (!matchesSearch) return false;

      if (statusFilter === "checked_in") return v.is_checked_in;
      if (statusFilter === "checked_out") return !v.is_checked_in;

      return true;
    });
  }, [visitors, searchTerm, statusFilter, residentMap]);

  const currentlyInsideCount = useMemo(() => {
    return visitors.filter((v) => v.is_checked_in).length;
  }, [visitors]);

  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formResident) {
      setFormError(t("errors.residentRequired"));
      return;
    }
    if (!formVisitorName.trim()) {
      setFormError(t("errors.nameRequired"));
      return;
    }
    const cleanPhone = formMobileNumber.replace(/\D/g, "");
    if (cleanPhone.length < 10) {
      setFormError(t("errors.phoneRequired"));
      return;
    }
    if (!formPurpose.trim()) {
      setFormError(t("errors.purposeRequired"));
      return;
    }

    setIsSubmitting(true);
    setFormError("");

    try {
      const created = await createVisitor({
        resident: formResident,
        visitor_name: formVisitorName.trim(),
        mobile_number: cleanPhone.slice(-10),
        purpose: formPurpose.trim(),
      });
      setVisitors((prev) => [created, ...prev]);
      setIsLoggingNew(false);
      setFormResident("");
      setFormVisitorName("");
      setFormMobileNumber("");
      setFormPurpose("");
      showToast(t("toasts.logged"));
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Failed to record visitor entry");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleCheckOut = async (visitor: Visitor) => {
    setCheckingOutId(visitor.id);
    try {
      const updated = await checkOutVisitor(visitor.id);
      setVisitors((prev) => prev.map((v) => (v.id === visitor.id ? updated : v)));
      showToast(t("toasts.checkedOut"));
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "Failed to check out visitor");
    } finally {
      setCheckingOutId(null);
    }
  };

  const formatDateTime = (isoString?: string | null) => {
    if (!isoString) return "—";
    try {
      const date = new Date(isoString);
      return date.toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return isoString;
    }
  };

  return (
    <div className="space-y-6">
      {/* Toast Alert */}
      {toastMessage && (
        <div className="fixed bottom-5 right-5 z-50 flex items-center gap-3 rounded-xl border border-emerald-100 bg-emerald-50 p-4 text-emerald-800 shadow-xl animate-bounce max-w-sm">
          <CheckCircle2 className="size-5 text-emerald-600 shrink-0" />
          <p className="text-xs font-semibold">{toastMessage}</p>
        </div>
      )}

      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-ink md:text-3xl font-display-lg">
            {t("title")}
          </h1>
          <p className="mt-1 text-sm text-ink-muted">{t("subtitle")}</p>
        </div>
        <button
          onClick={() => {
            setIsLoggingNew(true);
            setFormError("");
          }}
          className="inline-flex items-center justify-center gap-2 rounded-xl bg-accent px-4 py-2.5 text-sm font-semibold text-ink-inverse hover:bg-accent-hover hover:shadow-lg hover:shadow-blue-500/10 active:scale-[0.98] transition-all cursor-pointer self-start sm:self-auto"
        >
          <Plus className="size-4.5" />
          {t("logVisitor")}
        </button>
      </div>

      {/* KPI Stats summary */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
        <div className="rounded-2xl border border-border bg-surface-card p-4.5 shadow-sm">
          <span className="text-xs font-bold uppercase tracking-wider text-ink-faint">
            {t("totalLogged")}
          </span>
          <p className="mt-2 text-2xl font-extrabold tracking-tight text-ink">
            {visitors.length}
          </p>
        </div>
        <div className="rounded-2xl border border-border bg-surface-card p-4.5 shadow-sm">
          <span className="text-xs font-bold uppercase tracking-wider text-ink-faint">
            {t("checkedIn")}
          </span>
          <p className="mt-2 text-2xl font-extrabold tracking-tight text-accent">
            {currentlyInsideCount}
          </p>
        </div>
        <div className="col-span-2 sm:col-span-1 rounded-2xl border border-border bg-surface-card p-4.5 shadow-sm">
          <span className="text-xs font-bold uppercase tracking-wider text-ink-faint">
            {t("checkedOut")}
          </span>
          <p className="mt-2 text-2xl font-extrabold tracking-tight text-ink-muted">
            {visitors.length - currentlyInsideCount}
          </p>
        </div>
      </div>

      {/* Filter and Search Panel */}
      <div className="rounded-2xl border border-border bg-surface-card p-4 shadow-sm space-y-4">
        {/* Status Pills */}
        <div className="flex flex-wrap gap-2 border-b border-border pb-3">
          {[
            { id: "all", label: t("filterStatus") },
            { id: "checked_in", label: t("checkedIn") },
            { id: "checked_out", label: t("checkedOut") },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setStatusFilter(tab.id as typeof statusFilter)}
              className={`rounded-xl px-3 py-1.5 text-xs font-semibold transition-all cursor-pointer ${
                statusFilter === tab.id
                  ? "bg-surface-inverse text-ink-inverse shadow-xs"
                  : "bg-surface-page text-ink-muted hover:bg-surface-subtle hover:text-ink"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Search input */}
        <div className="relative">
          <Search className="absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-ink-faint" />
          <input
            type="text"
            placeholder={t("searchPlaceholder")}
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full rounded-xl border border-border bg-surface-page py-2 pl-9 pr-4 text-xs text-ink outline-none transition-all focus:border-accent focus:ring-2 focus:ring-accent/15"
          />
        </div>
      </div>

      {/* Main Content Area */}
      {isLoading ? (
        <div className="flex flex-col items-center justify-center gap-2 py-32 text-sm text-ink-muted">
          <LoaderCircle className="size-8 animate-spin text-accent" />
          <p className="font-semibold mt-2">{tCommon("authCheck")}</p>
        </div>
      ) : error ? (
        <div className="space-y-4 max-w-md mx-auto py-16 text-center">
          <div className="flex size-14 items-center justify-center rounded-full bg-status-critical-soft text-status-critical border border-status-critical/10 mx-auto">
            <AlertTriangle className="size-6" />
          </div>
          <h3 className="text-lg font-bold text-ink">{t("errors.loadFailed")}</h3>
          <p className="text-xs text-ink-muted leading-relaxed">{error}</p>
          <button
            onClick={handleReload}
            className="px-4 py-2 bg-surface-inverse text-ink-inverse text-xs font-semibold rounded-xl hover:opacity-90 transition-opacity cursor-pointer shadow-sm"
          >
            {tCommon("actions.retry")}
          </button>
        </div>
      ) : filteredVisitors.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-border p-12 text-center bg-surface-card space-y-3">
          <div className="flex size-12 items-center justify-center rounded-full bg-surface-page text-ink-faint mx-auto">
            <UserCheck className="size-6" />
          </div>
          <p className="text-sm font-semibold text-ink">{t("table.noVisitors")}</p>
          <p className="text-xs text-ink-muted">{t("table.noVisitorsSub")}</p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-2xl border border-border bg-surface-card shadow-sm">
          {/* Table for md+ */}
          <div className="hidden md:block overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-border bg-surface-page text-ink-muted font-bold uppercase tracking-wider">
                <tr>
                  <th className="px-5 py-3.5">{t("table.visitor")}</th>
                  <th className="px-5 py-3.5">{t("table.resident")}</th>
                  <th className="px-5 py-3.5">{t("table.purpose")}</th>
                  <th className="px-5 py-3.5">{t("table.entryTime")}</th>
                  <th className="px-5 py-3.5">{t("table.exitTime")}</th>
                  <th className="px-5 py-3.5">{t("table.status")}</th>
                  <th className="px-5 py-3.5 text-right">{t("table.actions")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {filteredVisitors.map((v) => {
                  const res = residentMap.get(v.resident);
                  const resName = res ? `${res.first_name} ${res.last_name}`.trim() : t("residentFallback");
                  const resUnit = res?.unit || "";

                  return (
                    <tr key={v.id} className="hover:bg-surface-subtle/50 transition-colors">
                      <td className="px-5 py-4">
                        <div className="flex items-center gap-3">
                          <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent text-xs font-bold">
                            {v.visitor_name[0]?.toUpperCase() || "V"}
                          </span>
                          <div>
                            <p className="font-semibold text-ink">{v.visitor_name}</p>
                            <p className="text-ink-muted text-[11px] flex items-center gap-1 mt-0.5">
                              <Phone className="size-3 text-ink-faint" />
                              {v.mobile_number}
                            </p>
                          </div>
                        </div>
                      </td>
                      <td className="px-5 py-4">
                        <div className="space-y-0.5">
                          <span className="font-medium text-ink">{resName}</span>
                          {resUnit && <p className="text-[11px] text-ink-faint">{resUnit}</p>}
                        </div>
                      </td>
                      <td className="px-5 py-4 font-medium text-ink-muted max-w-[180px] truncate">
                        {v.purpose}
                      </td>
                      <td className="px-5 py-4 font-mono text-[11px] text-ink-muted">
                        {formatDateTime(v.entry_time)}
                      </td>
                      <td className="px-5 py-4 font-mono text-[11px] text-ink-muted">
                        {formatDateTime(v.exit_time)}
                      </td>
                      <td className="px-5 py-4">
                        <StatusPill
                          label={v.is_checked_in ? t("checkedIn") : t("checkedOut")}
                          tone={v.is_checked_in ? "good" : "neutral"}
                        />
                      </td>
                      <td className="px-5 py-4 text-right">
                        {v.is_checked_in ? (
                          <button
                            onClick={() => handleCheckOut(v)}
                            disabled={checkingOutId === v.id}
                            className="inline-flex items-center gap-1 rounded-lg border border-border bg-surface-card px-3 py-1.5 text-xs font-bold text-ink hover:bg-surface-page hover:border-status-critical/30 hover:text-status-critical transition-colors cursor-pointer disabled:opacity-50"
                          >
                            {checkingOutId === v.id ? (
                              <>
                                <LoaderCircle className="size-3 animate-spin" />
                                <span>{t("actions.checkingOut")}</span>
                              </>
                            ) : (
                              <>
                                <LogOut className="size-3" />
                                <span>{t("actions.checkOut")}</span>
                              </>
                            )}
                          </button>
                        ) : (
                          <span className="text-xs text-ink-faint">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Mobile list view (< md) */}
          <div className="divide-y divide-border md:hidden">
            {filteredVisitors.map((v) => {
              const res = residentMap.get(v.resident);
              const resName = res ? `${res.first_name} ${res.last_name}`.trim() : t("residentFallback");

              return (
                <div key={v.id} className="p-4 space-y-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-center gap-3">
                      <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent text-xs font-bold">
                        {v.visitor_name[0]?.toUpperCase() || "V"}
                      </span>
                      <div>
                        <h4 className="text-sm font-bold text-ink">{v.visitor_name}</h4>
                        <p className="text-xs text-ink-muted flex items-center gap-1 mt-0.5">
                          <Phone className="size-3 text-ink-faint" />
                          {v.mobile_number}
                        </p>
                      </div>
                    </div>
                    <StatusPill
                      label={v.is_checked_in ? t("checkedIn") : t("checkedOut")}
                      tone={v.is_checked_in ? "good" : "neutral"}
                    />
                  </div>

                  <div className="rounded-xl bg-surface-page p-3 text-xs space-y-1.5 border border-border/60">
                    <div className="flex justify-between">
                      <span className="text-ink-faint">{t("table.resident")}:</span>
                      <span className="font-semibold text-ink">{resName}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-ink-faint">{t("table.purpose")}:</span>
                      <span className="font-medium text-ink-muted">{v.purpose}</span>
                    </div>
                    <div className="flex justify-between font-mono text-[11px]">
                      <span className="text-ink-faint">{t("table.entryTime")}:</span>
                      <span className="text-ink-muted">{formatDateTime(v.entry_time)}</span>
                    </div>
                    {v.exit_time && (
                      <div className="flex justify-between font-mono text-[11px]">
                        <span className="text-ink-faint">{t("table.exitTime")}:</span>
                        <span className="text-ink-muted">{formatDateTime(v.exit_time)}</span>
                      </div>
                    )}
                  </div>

                  {v.is_checked_in && (
                    <button
                      onClick={() => handleCheckOut(v)}
                      disabled={checkingOutId === v.id}
                      className="w-full flex items-center justify-center gap-1.5 rounded-xl border border-border bg-surface-card py-2 text-xs font-bold text-ink hover:bg-surface-page hover:text-status-critical transition-colors cursor-pointer disabled:opacity-50"
                    >
                      {checkingOutId === v.id ? (
                        <>
                          <LoaderCircle className="size-3.5 animate-spin" />
                          <span>{t("actions.checkingOut")}</span>
                        </>
                      ) : (
                        <>
                          <LogOut className="size-3.5" />
                          <span>{t("actions.checkOut")}</span>
                        </>
                      )}
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Log Visitor Modal */}
      {isLoggingNew && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 p-4 backdrop-blur-xs">
          <div className="relative w-full max-w-md rounded-2xl border border-border bg-surface-card p-6 shadow-2xl space-y-5 animate-in fade-in zoom-in-95 duration-200">
            <div className="flex items-start justify-between">
              <div>
                <h3 className="text-lg font-bold text-ink">{t("modal.title")}</h3>
                <p className="text-xs text-ink-muted mt-1">{t("modal.subtitle")}</p>
              </div>
              <button
                onClick={() => setIsLoggingNew(false)}
                className="rounded-lg p-1.5 text-ink-faint hover:bg-surface-page hover:text-ink transition-colors cursor-pointer"
              >
                <X className="size-5" />
              </button>
            </div>

            {formError && (
              <div className="flex items-center gap-2 rounded-xl border border-status-critical/30 bg-status-critical-soft px-4 py-2.5 text-xs text-status-critical">
                <AlertTriangle className="size-4 shrink-0" />
                <span>{formError}</span>
              </div>
            )}

            <form onSubmit={handleCreateSubmit} className="space-y-4">
              <div className="space-y-1.5">
                <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                  {t("modal.residentLabel")}
                </label>
                <select
                  value={formResident}
                  onChange={(e) => setFormResident(e.target.value)}
                  className="w-full rounded-xl border border-border bg-surface-page px-3 py-2 text-xs text-ink outline-none transition-all focus:border-accent focus:ring-2 focus:ring-accent/15 cursor-pointer"
                >
                  <option value="">{t("modal.selectResident")}</option>
                  {residents.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.first_name} {r.last_name} {r.unit ? `(${r.unit})` : ""}
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                  {t("modal.nameLabel")}
                </label>
                <input
                  type="text"
                  placeholder={t("modal.namePlaceholder")}
                  value={formVisitorName}
                  onChange={(e) => setFormVisitorName(e.target.value)}
                  className="w-full rounded-xl border border-border bg-surface-page px-3 py-2 text-xs text-ink outline-none transition-all focus:border-accent focus:ring-2 focus:ring-accent/15"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                  {t("modal.phoneLabel")}
                </label>
                <input
                  type="tel"
                  placeholder={t("modal.phonePlaceholder")}
                  value={formMobileNumber}
                  onChange={(e) => setFormMobileNumber(e.target.value)}
                  className="w-full rounded-xl border border-border bg-surface-page px-3 py-2 text-xs text-ink outline-none transition-all focus:border-accent focus:ring-2 focus:ring-accent/15"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                  {t("modal.purposeLabel")}
                </label>
                <input
                  type="text"
                  placeholder={t("modal.purposePlaceholder")}
                  value={formPurpose}
                  onChange={(e) => setFormPurpose(e.target.value)}
                  className="w-full rounded-xl border border-border bg-surface-page px-3 py-2 text-xs text-ink outline-none transition-all focus:border-accent focus:ring-2 focus:ring-accent/15"
                />
              </div>

              <div className="flex gap-2.5 pt-2">
                <button
                  type="button"
                  onClick={() => setIsLoggingNew(false)}
                  className="flex-1 rounded-xl border border-border bg-surface-page py-2.5 text-xs font-semibold text-ink-muted hover:bg-surface-subtle transition-colors cursor-pointer"
                >
                  {tCommon("actions.cancel")}
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="flex-1 rounded-xl bg-accent py-2.5 text-xs font-semibold text-ink-inverse hover:bg-accent-hover transition-colors disabled:opacity-50 cursor-pointer"
                >
                  {isSubmitting ? t("modal.submitting") : t("modal.submit")}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
