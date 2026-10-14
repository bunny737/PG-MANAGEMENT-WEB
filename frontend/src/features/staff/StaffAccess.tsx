"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowLeft,
  BarChart3,
  Building2,
  ChevronDown,
  ClipboardList,
  Globe,
  LayoutDashboard,
  Loader2,
  Phone,
  Mail,
  RotateCcw,
  Shield,
  UserCheck,
  UserX,
  Users,
  Wallet,
  X,
  type LucideIcon,
} from "lucide-react";
import { useTranslations } from "next-intl";
import {
  ApiError,
  assignStaffToProperty,
  getStaff,
  listProperties,
  listPropertyAssignments,
  unassignStaffFromProperty,
  updateStaff,
  type ModuleAccessEntry,
  type ModuleLevel,
  type Property,
  type PropertyStaffAssignment,
  type StaffUser,
} from "@/lib/api";
import { getInitials } from "@/lib/utils";
import { PermissionGate } from "@/components/shared/PermissionGate";
import { useModuleAccess } from "./useModuleAccess";

interface ModuleStyle {
  icon: LucideIcon;
  tile: string;
  text: string;
  on: string;
}

// Tailwind needs complete class names at build time, so these are spelled out per module.
const MODULE_STYLES: Record<string, ModuleStyle> = {
  dashboard: { icon: LayoutDashboard, tile: "bg-sky-50 text-sky-600", text: "text-sky-600", on: "bg-sky-500" },
  properties: { icon: Building2, tile: "bg-blue-50 text-blue-600", text: "text-blue-600", on: "bg-blue-600" },
  tenants: { icon: Users, tile: "bg-purple-50 text-purple-600", text: "text-purple-600", on: "bg-purple-600" },
  finance: { icon: Wallet, tile: "bg-emerald-50 text-emerald-600", text: "text-emerald-600", on: "bg-emerald-600" },
  reports: { icon: BarChart3, tile: "bg-orange-50 text-orange-600", text: "text-orange-600", on: "bg-orange-500" },
  complaints: { icon: AlertTriangle, tile: "bg-rose-50 text-rose-600", text: "text-rose-600", on: "bg-rose-500" },
  visitors: { icon: ClipboardList, tile: "bg-teal-50 text-teal-600", text: "text-teal-600", on: "bg-teal-600" },
};
const FALLBACK_STYLE: ModuleStyle = {
  icon: Shield,
  tile: "bg-slate-100 text-slate-600",
  text: "text-slate-600",
  on: "bg-slate-600",
};

function Switch({
  checked,
  onChange,
  label,
  onClass,
}: {
  checked: boolean;
  onChange: () => void;
  label: string;
  onClass: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={onChange}
      className={`relative inline-flex h-7 w-12 shrink-0 cursor-pointer items-center rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 ${
        checked ? onClass : "bg-slate-300 dark:bg-slate-600"
      }`}
    >
      <span
        className={`inline-block size-5 rounded-full bg-white shadow transition-transform ${
          checked ? "translate-x-6" : "translate-x-1"
        }`}
      />
    </button>
  );
}

export function StaffAccess({ staffId }: { staffId: string }) {
  const t = useTranslations("staff");

  const access = useModuleAccess(staffId);

  const [staff, setStaff] = useState<StaffUser | null>(null);
  const [staffMissing, setStaffMissing] = useState(false);
  const [statusBusy, setStatusBusy] = useState(false);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  // PG access
  const [pgOpen, setPgOpen] = useState(false);
  const [properties, setProperties] = useState<Property[]>([]);
  const [assignments, setAssignments] = useState<PropertyStaffAssignment[]>([]);
  const [pgLoading, setPgLoading] = useState(true);
  const [pgError, setPgError] = useState<string | null>(null);
  const [togglingProperty, setTogglingProperty] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getStaff(staffId)
      .then((data) => {
        if (!cancelled) setStaff(data);
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiError && (err.status === 404 || err.status === 403)) setStaffMissing(true);
      });
    return () => {
      cancelled = true;
    };
  }, [staffId, access.access?.role]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([listProperties(), listPropertyAssignments({ staff: staffId })])
      .then(([all, assigned]) => {
        if (cancelled) return;
        setProperties(all);
        setAssignments(assigned);
        setPgLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setPgError(err instanceof ApiError ? err.message : t("access.pgToggleError"));
        setPgLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [staffId, t]);

  const name = staff ? `${staff.first_name} ${staff.last_name || ""}`.trim() : "";

  const label = (key: string, fallback: string) => (t.has(key as never) ? t(key as never) : fallback);
  const moduleName = (entry: ModuleAccessEntry) => label(`access.modules.${entry.key}.name`, entry.key);
  const levelLabel = (entry: ModuleAccessEntry, level: ModuleLevel) =>
    level === "off"
      ? t("access.levels.off")
      : label(`access.modules.${entry.key}.${level}`, label(`access.levels.${level}`, level));

  const toggleStatus = async () => {
    if (!staff) return;
    const next = !staff.is_active;
    if (!next && !window.confirm(t("actions.confirmDeactivate", { name }))) return;
    setStatusBusy(true);
    setStatusError(null);
    try {
      setStaff(await updateStaff(staff.id, { is_active: next }));
    } catch (err) {
      setStatusError(err instanceof ApiError ? err.message : t("errors.genericError"));
    } finally {
      setStatusBusy(false);
    }
  };

  const toggleProperty = async (property: Property) => {
    const existing = assignments.find((a) => a.property === property.id);
    setTogglingProperty(property.id);
    setPgError(null);
    try {
      if (existing) {
        await unassignStaffFromProperty(existing.id);
        setAssignments((prev) => prev.filter((a) => a.id !== existing.id));
      } else {
        const created = await assignStaffToProperty(staffId, property.id);
        setAssignments((prev) => [...prev, created]);
      }
    } catch (err) {
      setPgError(err instanceof ApiError ? err.message : t("access.pgToggleError"));
    } finally {
      setTogglingProperty(null);
    }
  };

  const backLink = (
    <Link
      href="/staff"
      className="group inline-flex items-center gap-2 text-sm font-medium text-ink-muted transition-colors hover:text-ink"
    >
      <ArrowLeft className="size-4 transition-transform group-hover:-translate-x-0.5" />
      {t("access.backToStaff")}
    </Link>
  );

  if (access.status === "notfound" || staffMissing) {
    return (
      <div className="mx-auto w-full max-w-xl space-y-6">
        {backLink}
        <div className="rounded-2xl border border-dashed border-border bg-surface-card p-10 text-center">
          <div className="mx-auto flex size-12 items-center justify-center rounded-2xl bg-accent-soft text-accent">
            <UserX className="size-6" />
          </div>
          <h2 className="mt-4 text-base font-semibold text-ink">{t("access.notFoundTitle")}</h2>
          <p className="mt-1 text-sm text-ink-muted">{t("access.notFoundBody")}</p>
        </div>
      </div>
    );
  }

  if (access.status === "error") {
    return (
      <div className="mx-auto w-full max-w-xl space-y-6">
        {backLink}
        <div className="rounded-2xl border border-status-critical/20 bg-status-critical-soft p-6 text-center text-status-critical">
          <AlertTriangle className="mx-auto mb-2 size-6" />
          <p className="text-sm font-semibold">{t("access.loadFailed")}</p>
          <button
            type="button"
            onClick={() => void access.reload()}
            className="mt-3 rounded-lg bg-status-critical px-3 py-1.5 text-xs font-semibold text-white hover:opacity-90"
          >
            {t("access.retry")}
          </button>
        </div>
      </div>
    );
  }

  if (access.status === "loading" || !access.access) {
    return (
      <div className="mx-auto w-full max-w-xl space-y-6">
        {backLink}
        <div className="flex h-64 items-center justify-center rounded-2xl border border-border bg-surface-card">
          <Loader2 className="size-8 animate-spin text-accent" />
        </div>
      </div>
    );
  }

  const data = access.access;
  const pgCount = assignments.length;
  const pgSummary =
    pgCount === 0
      ? t("access.pgCountNone")
      : pgCount === 1
        ? t("access.pgCountOne")
        : t("access.pgCountMany", { count: pgCount });

  return (
    <div className="mx-auto w-full max-w-xl space-y-4">
      {backLink}

      {access.roleChanged && (
        <div className="flex items-start justify-between gap-3 rounded-xl border border-amber-300/50 bg-amber-50 p-3 text-xs font-medium text-amber-900">
          <span>{t("access.roleChangedNotice")}</span>
          <button type="button" onClick={access.dismissRoleChanged} aria-label={t("access.dismiss")}>
            <X className="size-4" />
          </button>
        </div>
      )}
      {access.error && (
        <div className="rounded-xl border border-status-critical/20 bg-status-critical-soft p-3 text-xs font-medium text-status-critical">
          {access.error === "save_failed" ? t("access.saveFailed") : `${t("access.saveFailed")} (${access.error})`}
        </div>
      )}
      {staff && !staff.is_active && (
        <div className="rounded-xl border border-border bg-surface-subtle p-3 text-xs text-ink-muted">
          {t("access.inactiveBanner")}
        </div>
      )}

      <section className="overflow-hidden rounded-3xl border border-border bg-surface-card p-5 shadow-sm">
        {/* Member header */}
        <div className="flex items-start justify-between gap-3 border-b border-border pb-4">
          <div className="flex min-w-0 items-center gap-3">
            <span className="flex size-14 shrink-0 items-center justify-center rounded-2xl bg-accent font-display text-base font-bold text-ink-inverse">
              {staff ? getInitials(name) : ""}
            </span>
            <div className="min-w-0">
              <h2 className="truncate font-display text-lg font-bold text-ink">{name || "…"}</h2>
              {staff?.email && (
                <p className="flex items-center gap-1.5 truncate text-xs text-ink-muted">
                  <Mail className="size-3.5 shrink-0 text-ink-faint" />
                  {staff.email}
                </p>
              )}
              {staff?.phone && (
                <p className="flex items-center gap-1.5 text-xs text-ink-muted">
                  <Phone className="size-3.5 shrink-0 text-ink-faint" />
                  {staff.phone}
                </p>
              )}
            </div>
          </div>
          <div className="flex shrink-0 flex-col items-end gap-2">
            {staff && (
              <span
                className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                  staff.is_active ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-600"
                }`}
              >
                <span className={`size-1.5 rounded-full ${staff.is_active ? "bg-emerald-500" : "bg-slate-400"}`} />
                {staff.is_active ? t("active") : t("inactive")}
              </span>
            )}
            <span className="inline-flex items-center gap-1 rounded-full bg-surface-subtle px-2.5 py-0.5 text-[11px] font-semibold text-ink-muted">
              <Shield className="size-3" />
              {t(`roles.${data.role}` as "roles.manager")}
            </span>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 border-b border-border py-3">
          {staff && (
            <button
              type="button"
              disabled={statusBusy}
              onClick={() => void toggleStatus()}
              className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors ${
                staff.is_active
                  ? "text-status-critical hover:bg-status-critical-soft"
                  : "text-emerald-600 hover:bg-emerald-50"
              }`}
            >
              {statusBusy ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : staff.is_active ? (
                <UserX className="size-3.5" />
              ) : (
                <UserCheck className="size-3.5" />
              )}
              {staff.is_active ? t("access.deactivate") : t("access.reactivate")}
            </button>
          )}
          {statusError && <span className="text-[11px] text-status-critical">{statusError}</span>}
        </div>

        {/* Module access */}
        <div className="pt-4">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-xs font-bold uppercase tracking-wider text-ink-faint">
              {t("access.moduleAccess")}
            </h3>
            <div className="flex items-center gap-2">
              {access.saving && (
                <span className="inline-flex items-center gap-1 text-[11px] text-ink-muted">
                  <Loader2 className="size-3 animate-spin" />
                  {t("access.saving")}
                </span>
              )}
              <span
                className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                  data.customized ? "bg-accent-soft text-accent" : "bg-surface-subtle text-ink-muted"
                }`}
              >
                {data.customized ? t("access.customizedBadge") : t("access.defaultsBadge")}
              </span>
            </div>
          </div>

          <ul className="mt-2 divide-y divide-border">
            {data.modules.map((entry) => {
              const style = MODULE_STYLES[entry.key] ?? FALLBACK_STYLE;
              const Icon = style.icon;
              const level = access.levels[entry.key] ?? entry.level;
              const onLevels = entry.levels.filter((l) => l !== "off");
              const hasPicker = onLevels.length > 1;
              const isOpen = expanded === entry.key;
              return (
                <li key={entry.key} className="py-3">
                  <div className="flex items-center gap-3">
                    <span className={`flex size-11 shrink-0 items-center justify-center rounded-xl ${style.tile}`}>
                      <Icon className="size-5" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-semibold text-ink">{moduleName(entry)}</p>
                      <p className={`text-xs ${level === "off" ? "text-ink-faint" : style.text}`}>
                        {levelLabel(entry, level)}
                      </p>
                    </div>
                    {hasPicker && (
                      <button
                        type="button"
                        onClick={() => setExpanded(isOpen ? null : entry.key)}
                        aria-expanded={isOpen}
                        aria-label={moduleName(entry)}
                        className="rounded-lg p-1.5 text-ink-faint transition-colors hover:bg-surface-subtle hover:text-ink"
                      >
                        <ChevronDown className={`size-4 transition-transform ${isOpen ? "rotate-180" : ""}`} />
                      </button>
                    )}
                    <Switch
                      checked={level !== "off"}
                      onChange={() => access.toggle(entry.key)}
                      label={moduleName(entry)}
                      onClass={style.on}
                    />
                  </div>

                  {isOpen && (
                    <div className="ml-14 mt-3 space-y-2 rounded-xl bg-surface-page p-3">
                      <div role="radiogroup" aria-label={moduleName(entry)} className="space-y-1.5">
                        {onLevels.map((lvl) => (
                          <label
                            key={lvl}
                            className="flex cursor-pointer items-center gap-2.5 text-sm text-ink"
                          >
                            <input
                              type="radio"
                              name={`level-${entry.key}`}
                              checked={level === lvl}
                              onChange={() => access.setLevel(entry.key, lvl)}
                              className="size-4 border-border text-accent focus:ring-accent"
                            />
                            {levelLabel(entry, lvl)}
                          </label>
                        ))}
                      </div>
                      {t.has(`access.modules.${entry.key}.hint` as never) && (
                        <p className="text-[11px] leading-relaxed text-ink-faint">
                          {t(`access.modules.${entry.key}.hint` as never)}
                        </p>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>

          {data.customized && (
            <button
              type="button"
              onClick={access.resetToDefaults}
              className="mt-2 inline-flex items-center gap-1.5 text-xs font-medium text-accent hover:underline"
            >
              <RotateCcw className="size-3.5" />
              {t("access.resetDefaults")}
            </button>
          )}
        </div>

        {/* PG access */}
        <PermissionGate permission="assign_staff_to_properties">
          <div className="mt-4 border-t border-border pt-2">
            <button
              type="button"
              onClick={() => setPgOpen((open) => !open)}
              aria-expanded={pgOpen}
              className="flex w-full items-center gap-3 py-3 text-left"
            >
              <span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-sky-50 text-sky-600">
                <Globe className="size-5" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-semibold text-ink">{t("access.pgAccess")}</span>
                <span className="block text-xs text-purple-600">{pgLoading ? "…" : pgSummary}</span>
              </span>
              <ChevronDown className={`size-4 text-ink-faint transition-transform ${pgOpen ? "rotate-180" : ""}`} />
            </button>

            {pgOpen && (
              <div className="space-y-2 pb-2">
                {pgError && (
                  <div className="rounded-xl border border-status-critical/20 bg-status-critical-soft p-3 text-xs font-medium text-status-critical">
                    {pgError}
                  </div>
                )}
                {pgLoading ? (
                  <div className="flex h-24 items-center justify-center">
                    <Loader2 className="size-6 animate-spin text-accent" />
                  </div>
                ) : properties.length === 0 ? (
                  <p className="py-4 text-center text-sm text-ink-muted">{t("modal.noProperties")}</p>
                ) : (
                  <div className="max-h-72 space-y-2 overflow-y-auto">
                    {properties.map((property) => {
                      const isAssigned = assignments.some((a) => a.property === property.id);
                      const isToggling = togglingProperty === property.id;
                      return (
                        <label
                          key={property.id}
                          className="flex cursor-pointer items-center justify-between gap-3 rounded-xl border border-border bg-surface-page px-3.5 py-2.5 hover:bg-surface-subtle"
                        >
                          <span className="flex items-center gap-2.5">
                            <Building2 className="size-4 text-ink-faint" />
                            <span className="text-sm font-medium text-ink">{property.name}</span>
                          </span>
                          {isToggling ? (
                            <Loader2 className="size-4 animate-spin text-accent" />
                          ) : (
                            <input
                              type="checkbox"
                              checked={isAssigned}
                              onChange={() => void toggleProperty(property)}
                              className="size-4 rounded border-border text-accent focus:ring-accent"
                            />
                          )}
                        </label>
                      );
                    })}
                  </div>
                )}
                <p className="text-[11px] text-ink-faint">{t("modal.propertiesHelp")}</p>
              </div>
            )}
          </div>
        </PermissionGate>
      </section>

      <p className="px-1 text-[11px] leading-relaxed text-ink-faint">{t("access.applyNote")}</p>
    </div>
  );
}
