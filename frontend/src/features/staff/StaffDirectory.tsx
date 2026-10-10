"use client";

import React, { useState, useEffect, useMemo } from "react";
import {
  Search,
  Phone,
  Mail,
  UserPlus,
  KeyRound,
  UserX,
  UserCheck,
  Copy,
  Check,
  Eye,
  EyeOff,
  AlertTriangle,
  Loader2,
  X,
  Shield,
  Sparkles,
} from "lucide-react";
import { useTranslations } from "next-intl";
import {
  listStaff,
  createStaff,
  updateStaff,
  setStaffPassword,
  type StaffUser,
  type CreateStaffPayload,
  ApiError,
} from "@/lib/api";
import { getInitials } from "@/lib/utils";
import { generateSecurePassword } from "@/lib/passwords";

function normalizePhone(val: string): string | null {
  const digits = val.replace(/\D/g, "");
  if (digits.length === 10 && /^[6-9]/.test(digits)) return digits;
  if (digits.length === 11 && digits.startsWith("0") && /^[6-9]/.test(digits.slice(1)))
    return digits.slice(1);
  if (digits.length === 12 && digits.startsWith("91") && /^[6-9]/.test(digits.slice(2)))
    return digits.slice(2);
  return null;
}

export function StaffDirectory() {
  const t = useTranslations("staff");
  const tCommon = useTranslations("common");

  const [staffList, setStaffList] = useState<StaffUser[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [searchTerm, setSearchTerm] = useState("");
  const [roleFilter, setRoleFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");

  // Create Staff Modal State
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [createForm, setCreateForm] = useState<{
    firstName: string;
    lastName: string;
    phone: string;
    email: string;
    role: "manager" | "receptionist";
    password: string;
  }>({
    firstName: "",
    lastName: "",
    phone: "",
    email: "",
    role: "manager",
    password: "",
  });
  const [showCreatePassword, setShowCreatePassword] = useState(false);
  const [createErrors, setCreateErrors] = useState<Record<string, string>>({});
  const [isCreating, setIsCreating] = useState(false);

  // Reset Password Modal State
  const [resetTarget, setResetTarget] = useState<StaffUser | null>(null);
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showResetPassword, setShowResetPassword] = useState(false);
  const [resetErrors, setResetErrors] = useState<Record<string, string>>({});
  const [isResetting, setIsResetting] = useState(false);

  // One-Time Password Reveal Modal State
  const [revealedPassword, setRevealedPassword] = useState<{
    staffName: string;
    phone: string;
    password: string;
    action: "created" | "reset";
  } | null>(null);
  const [copied, setCopied] = useState(false);

  // Status Action in Progress
  const [statusActionId, setStatusActionId] = useState<string | null>(null);

  const fetchStaff = React.useCallback(() => {
    setIsLoading(true);
    setError(null);
    listStaff()
      .then((data) => {
        setStaffList(data);
        setIsLoading(false);
      })
      .catch((err) => {
        setError(err instanceof ApiError ? err.message : t("errors.genericError"));
        setIsLoading(false);
      });
  }, [t]);

  useEffect(() => {
    let cancelled = false;
    listStaff()
      .then((data) => {
        if (cancelled) return;
        setStaffList(data);
        setIsLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : t("errors.genericError"));
        setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [t]);

  const handleCopyPassword = (pwd: string) => {
    navigator.clipboard.writeText(pwd);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const errors: Record<string, string> = {};

    if (!createForm.firstName.trim()) {
      errors.firstName = t("errors.firstNameRequired");
    }

    const normPhone = normalizePhone(createForm.phone);
    if (!createForm.phone.trim()) {
      errors.phone = t("errors.phoneRequired");
    } else if (!normPhone) {
      errors.phone = t("errors.phoneInvalid");
    }

    if (!createForm.password.trim() && !createForm.email.trim()) {
      errors.password = t("errors.passwordOrEmailRequired");
    }

    if (createForm.password && createForm.password.length < 6) {
      errors.password = t("errors.passwordRequired");
    }

    if (Object.keys(errors).length > 0) {
      setCreateErrors(errors);
      return;
    }

    setCreateErrors({});
    setIsCreating(true);

    try {
      const payload: CreateStaffPayload = {
        first_name: createForm.firstName.trim(),
        last_name: createForm.lastName.trim() || undefined,
        phone: normPhone!,
        email: createForm.email.trim() || null,
        role: createForm.role,
        password: createForm.password || undefined,
      };

      const created = await createStaff(payload);
      setIsCreating(false);
      setIsCreateOpen(false);

      const staffName = `${created.first_name} ${created.last_name || ""}`.trim();
      const enteredPassword = createForm.password;

      // Reset form
      setCreateForm({
        firstName: "",
        lastName: "",
        phone: "",
        email: "",
        role: "manager",
        password: "",
      });

      // Update staff list
      setStaffList((prev) => [created, ...prev]);

      // If initial password was set, reveal it once
      if (enteredPassword) {
        setRevealedPassword({
          staffName,
          phone: created.phone,
          password: enteredPassword,
          action: "created",
        });
      }
    } catch (err) {
      setIsCreating(false);
      if (err instanceof ApiError) {
        const phoneErr = err.fieldError("phone");
        const emailErr = err.fieldError("email");
        const pwdErr = err.fieldError("password");
        const nonFieldErr = err.fieldError("non_field_errors") ?? err.fieldError("detail");

        const newErrors: Record<string, string> = {};
        if (phoneErr) {
          newErrors.phone = phoneErr.includes("already active") || phoneErr.includes("taken")
            ? t("errors.phoneTaken")
            : phoneErr;
        }
        if (emailErr) {
          newErrors.email = emailErr.includes("already active") || emailErr.includes("taken")
            ? t("errors.emailTaken")
            : emailErr;
        }
        if (pwdErr) newErrors.password = pwdErr;
        if (nonFieldErr) newErrors.form = nonFieldErr;

        if (Object.keys(newErrors).length === 0) {
          newErrors.form = err.message;
        }
        setCreateErrors(newErrors);
      } else {
        setCreateErrors({ form: t("errors.genericError") });
      }
    }
  };

  const handleResetSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!resetTarget) return;

    const errors: Record<string, string> = {};
    if (!newPassword) {
      errors.newPassword = t("errors.passwordRequired");
    } else if (newPassword.length < 6) {
      errors.newPassword = t("errors.passwordRequired");
    }

    if (newPassword !== confirmPassword) {
      errors.confirmPassword = t("errors.passwordMismatch");
    }

    if (Object.keys(errors).length > 0) {
      setResetErrors(errors);
      return;
    }

    setResetErrors({});
    setIsResetting(true);

    try {
      await setStaffPassword(resetTarget.id, newPassword);
      setIsResetting(false);
      const targetUser = resetTarget;
      const pwd = newPassword;

      setResetTarget(null);
      setNewPassword("");
      setConfirmPassword("");

      // Reveal once
      setRevealedPassword({
        staffName: `${targetUser.first_name} ${targetUser.last_name || ""}`.trim(),
        phone: targetUser.phone,
        password: pwd,
        action: "reset",
      });
    } catch (err) {
      setIsResetting(false);
      if (err instanceof ApiError) {
        setResetErrors({
          form: err.fieldError("password") ?? err.fieldError("detail") ?? err.message,
        });
      } else {
        setResetErrors({ form: t("errors.genericError") });
      }
    }
  };

  const handleToggleActive = async (staff: StaffUser) => {
    const nextActive = !staff.is_active;
    const name = `${staff.first_name} ${staff.last_name || ""}`.trim();

    if (!nextActive) {
      const confirmed = window.confirm(t("actions.confirmDeactivate", { name }));
      if (!confirmed) return;
    }

    setStatusActionId(staff.id);
    try {
      const updated = await updateStaff(staff.id, { is_active: nextActive });
      setStaffList((prev) => prev.map((s) => (s.id === staff.id ? updated : s)));
    } catch (err) {
      if (err instanceof ApiError) {
        const phoneErr = err.fieldError("phone");
        const emailErr = err.fieldError("email");
        if (phoneErr) {
          alert(`${t("errors.phoneTaken")}: ${phoneErr}`);
        } else if (emailErr) {
          alert(`${t("errors.emailTaken")}: ${emailErr}`);
        } else {
          alert(err.message);
        }
      } else {
        alert(t("errors.genericError"));
      }
    } finally {
      setStatusActionId(null);
    }
  };

  const filteredStaff = useMemo(() => {
    return staffList.filter((staff) => {
      const fullName = `${staff.first_name} ${staff.last_name || ""}`.toLowerCase();
      const query = searchTerm.toLowerCase().trim();
      const matchesSearch =
        !query ||
        fullName.includes(query) ||
        (staff.phone && staff.phone.includes(query)) ||
        (staff.email && staff.email.toLowerCase().includes(query));

      const matchesRole = roleFilter === "all" || staff.role === roleFilter;
      const matchesStatus =
        statusFilter === "all" ||
        (statusFilter === "active" && staff.is_active) ||
        (statusFilter === "inactive" && !staff.is_active);

      return matchesSearch && matchesRole && matchesStatus;
    });
  }, [staffList, searchTerm, roleFilter, statusFilter]);

  return (
    <div className="space-y-6">
      {/* Top Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="font-display text-2xl font-bold tracking-tight text-ink md:text-3xl">
            {t("title")}
          </h1>
          <p className="mt-1 text-sm text-ink-muted">{t("subtitle")}</p>
        </div>
        <button
          onClick={() => {
            setCreateForm({
              firstName: "",
              lastName: "",
              phone: "",
              email: "",
              role: "manager",
              password: "",
            });
            setCreateErrors({});
            setIsCreateOpen(true);
          }}
          className="inline-flex items-center justify-center gap-2 rounded-xl bg-accent px-4 py-2.5 text-sm font-semibold text-ink-inverse shadow-sm transition-all hover:bg-accent-hover active:scale-[0.98]"
        >
          <UserPlus className="size-4.5" />
          {t("addStaff")}
        </button>
      </div>

      {/* Filter and Search Bar */}
      <div className="flex flex-col gap-3 rounded-2xl border border-border bg-surface-card p-3 shadow-xs sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="absolute inset-y-0 left-3 my-auto size-4 text-ink-faint" />
          <input
            type="text"
            placeholder={t("searchPlaceholder")}
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full rounded-xl border border-border bg-surface-page py-2 pl-9 pr-3 text-sm text-ink outline-none transition-all focus:border-accent focus:ring-2 focus:ring-accent/10"
          />
        </div>

        <div className="flex items-center gap-2">
          <select
            value={roleFilter}
            onChange={(e) => setRoleFilter(e.target.value)}
            className="rounded-xl border border-border bg-surface-page px-3 py-2 text-sm font-medium text-ink outline-none focus:border-accent"
          >
            <option value="all">{t("filterRole")}</option>
            <option value="manager">{t("roles.manager")}</option>
            <option value="receptionist">{t("roles.receptionist")}</option>
          </select>

          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="rounded-xl border border-border bg-surface-page px-3 py-2 text-sm font-medium text-ink outline-none focus:border-accent"
          >
            <option value="all">{t("filterStatus")}</option>
            <option value="active">{t("active")}</option>
            <option value="inactive">{t("inactive")}</option>
          </select>
        </div>
      </div>

      {/* Table / List View */}
      {isLoading ? (
        <div className="flex h-64 flex-col items-center justify-center gap-3 rounded-2xl border border-border bg-surface-card">
          <Loader2 className="size-8 animate-spin text-accent" />
          <p className="text-sm font-medium text-ink-muted">{tCommon("authCheck")}</p>
        </div>
      ) : error ? (
        <div className="rounded-2xl border border-status-critical/20 bg-status-critical-soft p-6 text-center text-status-critical">
          <AlertTriangle className="mx-auto mb-2 size-6" />
          <p className="text-sm font-semibold">{error}</p>
          <button
            onClick={fetchStaff}
            className="mt-3 rounded-lg bg-status-critical px-3 py-1.5 text-xs font-semibold text-white hover:opacity-90"
          >
            {tCommon("actions.retry")}
          </button>
        </div>
      ) : filteredStaff.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-border bg-surface-card p-12 text-center">
          <div className="flex size-12 items-center justify-center rounded-2xl bg-accent-soft text-accent">
            <UserX className="size-6" />
          </div>
          <h3 className="mt-4 text-base font-semibold text-ink">{t("table.noStaff")}</h3>
          <p className="mt-1 text-sm text-ink-muted">{t("table.noStaffSub")}</p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-2xl border border-border bg-surface-card shadow-xs">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-border bg-surface-subtle text-xs font-semibold uppercase tracking-wider text-ink-muted">
                <tr>
                  <th scope="col" className="px-6 py-3.5">
                    {t("table.name")}
                  </th>
                  <th scope="col" className="px-6 py-3.5">
                    {t("table.contact")}
                  </th>
                  <th scope="col" className="px-6 py-3.5">
                    {t("table.role")}
                  </th>
                  <th scope="col" className="px-6 py-3.5">
                    {t("table.status")}
                  </th>
                  <th scope="col" className="px-6 py-3.5 text-right">
                    {t("table.actions")}
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {filteredStaff.map((staff) => {
                  const fullName = `${staff.first_name} ${staff.last_name || ""}`.trim();
                  const initials = getInitials(fullName);

                  return (
                    <tr
                      key={staff.id}
                      className="transition-colors hover:bg-surface-subtle/50"
                    >
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-3">
                          <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-linear-to-br from-accent/20 to-accent/10 font-display text-sm font-bold text-accent">
                            {initials}
                          </span>
                          <div>
                            <p className="font-semibold text-ink">{fullName}</p>
                            <p className="font-mono text-xs text-ink-faint">
                              {staff.id.slice(0, 8)}
                            </p>
                          </div>
                        </div>
                      </td>
                      <td className="px-6 py-4">
                        <div className="space-y-1">
                          <a
                            href={`tel:${staff.phone}`}
                            className="flex items-center gap-1.5 text-xs font-medium text-ink hover:text-accent"
                          >
                            <Phone className="size-3.5 text-ink-faint" />
                            {staff.phone}
                          </a>
                          {staff.email ? (
                            <a
                              href={`mailto:${staff.email}`}
                              className="flex items-center gap-1.5 text-xs text-ink-muted hover:text-accent"
                            >
                              <Mail className="size-3.5 text-ink-faint" />
                              {staff.email}
                            </a>
                          ) : (
                            <span className="text-[11px] text-ink-faint italic">
                              {t("table.phoneOnly")}
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-6 py-4">
                        <span
                          className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold capitalize ${
                            staff.role === "manager"
                              ? "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300"
                              : "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300"
                          }`}
                        >
                          <Shield className="size-3" />
                          {t(`roles.${staff.role}` as "roles.manager")}
                        </span>
                      </td>
                      <td className="px-6 py-4">
                        <span
                          className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${
                            staff.is_active
                              ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400"
                              : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400"
                          }`}
                        >
                          <span
                            className={`size-1.5 rounded-full ${
                              staff.is_active ? "bg-emerald-500" : "bg-slate-400"
                            }`}
                          />
                          {staff.is_active ? t("active") : t("inactive")}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <button
                            onClick={() => {
                              setResetTarget(staff);
                              setNewPassword("");
                              setConfirmPassword("");
                              setResetErrors({});
                            }}
                            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-xs font-medium text-ink-muted transition-colors hover:bg-surface-subtle hover:text-ink"
                            title={t("actions.resetPassword")}
                          >
                            <KeyRound className="size-3.5 text-accent" />
                            <span className="hidden sm:inline">
                              {t("actions.resetPassword")}
                            </span>
                          </button>

                          <button
                            disabled={statusActionId === staff.id}
                            onClick={() => handleToggleActive(staff)}
                            className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors ${
                              staff.is_active
                                ? "text-status-critical hover:bg-status-critical-soft"
                                : "text-emerald-600 hover:bg-emerald-50"
                            }`}
                          >
                            {statusActionId === staff.id ? (
                              <Loader2 className="size-3.5 animate-spin" />
                            ) : staff.is_active ? (
                              <>
                                <UserX className="size-3.5" />
                                <span className="hidden sm:inline">
                                  {t("actions.deactivate")}
                                </span>
                              </>
                            ) : (
                              <>
                                <UserCheck className="size-3.5" />
                                <span className="hidden sm:inline">
                                  {t("actions.activate")}
                                </span>
                              </>
                            )}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* CREATE STAFF MODAL */}
      {isCreateOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-xs">
          <div className="w-full max-w-lg rounded-2xl border border-border bg-surface-card p-6 shadow-2xl animate-in fade-in zoom-in-95 duration-200">
            <div className="flex items-center justify-between border-b border-border pb-4">
              <div>
                <h3 className="font-display text-lg font-bold text-ink">
                  {t("modal.createTitle")}
                </h3>
                <p className="text-xs text-ink-muted">{t("modal.createSubtitle")}</p>
              </div>
              <button
                onClick={() => setIsCreateOpen(false)}
                className="rounded-lg p-1.5 text-ink-faint transition-colors hover:bg-surface-subtle hover:text-ink"
              >
                <X className="size-5" />
              </button>
            </div>

            <form onSubmit={handleCreateSubmit} className="mt-4 space-y-4">
              {createErrors.form && (
                <div className="rounded-xl border border-status-critical/20 bg-status-critical-soft p-3 text-xs font-medium text-status-critical">
                  {createErrors.form}
                </div>
              )}

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-ink-muted">
                    {t("modal.firstName")} *
                  </label>
                  <input
                    type="text"
                    required
                    value={createForm.firstName}
                    onChange={(e) =>
                      setCreateForm({ ...createForm, firstName: e.target.value })
                    }
                    className="w-full rounded-xl border border-border bg-surface-page px-3 py-2 text-sm text-ink outline-none focus:border-accent"
                    placeholder={t("modal.placeholderFirstName")}
                  />
                  {createErrors.firstName && (
                    <p className="text-[11px] text-status-critical">
                      {createErrors.firstName}
                    </p>
                  )}
                </div>

                <div className="space-y-1">
                  <label className="text-xs font-semibold text-ink-muted">
                    {t("modal.lastName")}
                  </label>
                  <input
                    type="text"
                    value={createForm.lastName}
                    onChange={(e) =>
                      setCreateForm({ ...createForm, lastName: e.target.value })
                    }
                    className="w-full rounded-xl border border-border bg-surface-page px-3 py-2 text-sm text-ink outline-none focus:border-accent"
                    placeholder={t("modal.placeholderLastName")}
                  />
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-xs font-semibold text-ink-muted">
                  {t("modal.phone")} *
                </label>
                <div className="relative">
                  <Phone className="absolute inset-y-0 left-3 my-auto size-4 text-ink-faint" />
                  <input
                    type="tel"
                    required
                    value={createForm.phone}
                    onChange={(e) =>
                      setCreateForm({ ...createForm, phone: e.target.value })
                    }
                    placeholder="9876543210"
                    className="w-full rounded-xl border border-border bg-surface-page py-2 pl-9 pr-3 text-sm text-ink outline-none focus:border-accent"
                  />
                </div>
                <p className="text-[11px] text-ink-faint">{t("modal.phoneHelp")}</p>
                {createErrors.phone && (
                  <p className="text-[11px] text-status-critical">
                    {createErrors.phone}
                  </p>
                )}
              </div>

              <div className="space-y-1">
                <label className="text-xs font-semibold text-ink-muted">
                  {t("modal.email")}
                </label>
                <div className="relative">
                  <Mail className="absolute inset-y-0 left-3 my-auto size-4 text-ink-faint" />
                  <input
                    type="email"
                    value={createForm.email}
                    onChange={(e) =>
                      setCreateForm({ ...createForm, email: e.target.value })
                    }
                    placeholder={t("modal.placeholderEmail")}
                    className="w-full rounded-xl border border-border bg-surface-page py-2 pl-9 pr-3 text-sm text-ink outline-none focus:border-accent"
                  />
                </div>
                <p className="text-[11px] text-ink-faint">{t("modal.emailHelp")}</p>
                {createErrors.email && (
                  <p className="text-[11px] text-status-critical">
                    {createErrors.email}
                  </p>
                )}
              </div>

              <div className="space-y-1">
                <label className="text-xs font-semibold text-ink-muted">
                  {t("modal.role")} *
                </label>
                <select
                  value={createForm.role}
                  onChange={(e) =>
                    setCreateForm({
                      ...createForm,
                      role: e.target.value as "manager" | "receptionist",
                    })
                  }
                  className="w-full rounded-xl border border-border bg-surface-page px-3 py-2 text-sm text-ink outline-none focus:border-accent"
                >
                  <option value="manager">{t("roles.manager")}</option>
                  <option value="receptionist">{t("roles.receptionist")}</option>
                </select>
              </div>

              <div className="space-y-1">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-semibold text-ink-muted">
                    {t("modal.password")}
                  </label>
                  <button
                    type="button"
                    onClick={() =>
                      setCreateForm({
                        ...createForm,
                        password: generateSecurePassword({
                          firstName: createForm.firstName,
                          lastName: createForm.lastName,
                          email: createForm.email,
                          phone: createForm.phone,
                        }),
                      })
                    }
                    className="inline-flex items-center gap-1 text-[11px] font-medium text-accent hover:underline"
                  >
                    <Sparkles className="size-3" />
                    {t("modal.autoGenerate")}
                  </button>
                </div>
                <div className="relative">
                  <input
                    type={showCreatePassword ? "text" : "password"}
                    value={createForm.password}
                    onChange={(e) =>
                      setCreateForm({ ...createForm, password: e.target.value })
                    }
                    placeholder="••••••••"
                    className="w-full rounded-xl border border-border bg-surface-page py-2 pl-3 pr-10 text-sm text-ink outline-none focus:border-accent"
                  />
                  <button
                    type="button"
                    onClick={() => setShowCreatePassword(!showCreatePassword)}
                    className="absolute inset-y-0 right-0 flex items-center pr-3 text-ink-faint hover:text-ink"
                  >
                    {showCreatePassword ? (
                      <EyeOff className="size-4" />
                    ) : (
                      <Eye className="size-4" />
                    )}
                  </button>
                </div>
                <p className="text-[11px] text-ink-faint">{t("modal.passwordHelp")}</p>
                {createErrors.password && (
                  <p className="text-[11px] text-status-critical">
                    {createErrors.password}
                  </p>
                )}
              </div>

              <div className="flex items-center justify-end gap-3 pt-3 border-t border-border">
                <button
                  type="button"
                  onClick={() => setIsCreateOpen(false)}
                  className="rounded-xl border border-border px-4 py-2 text-sm font-semibold text-ink-muted transition-colors hover:bg-surface-subtle"
                >
                  {t("modal.cancel")}
                </button>
                <button
                  type="submit"
                  disabled={isCreating}
                  className="inline-flex items-center justify-center gap-2 rounded-xl bg-accent px-4 py-2 text-sm font-semibold text-ink-inverse shadow-sm transition-all hover:bg-accent-hover active:scale-[0.98] disabled:opacity-50"
                >
                  {isCreating ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : (
                    <UserPlus className="size-4" />
                  )}
                  {t("modal.createButton")}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* RESET PASSWORD MODAL */}
      {resetTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-xs">
          <div className="w-full max-w-md rounded-2xl border border-border bg-surface-card p-6 shadow-2xl animate-in fade-in zoom-in-95 duration-200">
            <div className="flex items-center justify-between border-b border-border pb-4">
              <div>
                <h3 className="font-display text-lg font-bold text-ink">
                  {t("modal.resetTitle")}
                </h3>
                <p className="text-xs text-ink-muted">
                  {t("modal.resetSubtitle", {
                    name: `${resetTarget.first_name} ${resetTarget.last_name || ""}`.trim(),
                  })}
                </p>
              </div>
              <button
                onClick={() => setResetTarget(null)}
                className="rounded-lg p-1.5 text-ink-faint transition-colors hover:bg-surface-subtle hover:text-ink"
              >
                <X className="size-5" />
              </button>
            </div>

            <form onSubmit={handleResetSubmit} className="mt-4 space-y-4">
              {resetErrors.form && (
                <div className="rounded-xl border border-status-critical/20 bg-status-critical-soft p-3 text-xs font-medium text-status-critical">
                  {resetErrors.form}
                </div>
              )}

              <div className="space-y-1">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-semibold text-ink-muted">
                    {t("modal.newPassword")} *
                  </label>
                  <button
                    type="button"
                    onClick={() => {
                      const pwd = generateSecurePassword({
                        firstName: resetTarget?.first_name,
                        lastName: resetTarget?.last_name,
                        email: resetTarget?.email ?? undefined,
                        phone: resetTarget?.phone,
                      });
                      setNewPassword(pwd);
                      setConfirmPassword(pwd);
                    }}
                    className="inline-flex items-center gap-1 text-[11px] font-medium text-accent hover:underline"
                  >
                    <Sparkles className="size-3" />
                    {t("modal.autoGenerate")}
                  </button>
                </div>
                <div className="relative">
                  <input
                    type={showResetPassword ? "text" : "password"}
                    required
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    placeholder="••••••••"
                    className="w-full rounded-xl border border-border bg-surface-page py-2 pl-3 pr-10 text-sm text-ink outline-none focus:border-accent"
                  />
                  <button
                    type="button"
                    onClick={() => setShowResetPassword(!showResetPassword)}
                    className="absolute inset-y-0 right-0 flex items-center pr-3 text-ink-faint hover:text-ink"
                  >
                    {showResetPassword ? (
                      <EyeOff className="size-4" />
                    ) : (
                      <Eye className="size-4" />
                    )}
                  </button>
                </div>
                {resetErrors.newPassword && (
                  <p className="text-[11px] text-status-critical">
                    {resetErrors.newPassword}
                  </p>
                )}
              </div>

              <div className="space-y-1">
                <label className="text-xs font-semibold text-ink-muted">
                  {t("modal.confirmPassword")} *
                </label>
                <input
                  type={showResetPassword ? "text" : "password"}
                  required
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full rounded-xl border border-border bg-surface-page py-2 px-3 text-sm text-ink outline-none focus:border-accent"
                />
                {resetErrors.confirmPassword && (
                  <p className="text-[11px] text-status-critical">
                    {resetErrors.confirmPassword}
                  </p>
                )}
              </div>

              <div className="flex items-center justify-end gap-3 pt-3 border-t border-border">
                <button
                  type="button"
                  onClick={() => setResetTarget(null)}
                  className="rounded-xl border border-border px-4 py-2 text-sm font-semibold text-ink-muted transition-colors hover:bg-surface-subtle"
                >
                  {t("modal.cancel")}
                </button>
                <button
                  type="submit"
                  disabled={isResetting}
                  className="inline-flex items-center justify-center gap-2 rounded-xl bg-accent px-4 py-2 text-sm font-semibold text-ink-inverse shadow-sm transition-all hover:bg-accent-hover active:scale-[0.98] disabled:opacity-50"
                >
                  {isResetting ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : (
                    <KeyRound className="size-4" />
                  )}
                  {t("modal.resetButton")}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ONE-TIME PASSWORD DISPLAY MODAL */}
      {revealedPassword && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-xs">
          <div className="w-full max-w-md rounded-2xl border border-amber-300/40 bg-surface-card p-6 shadow-2xl animate-in fade-in zoom-in-95 duration-200">
            <div className="flex items-center gap-3">
              <span className="flex size-10 items-center justify-center rounded-xl bg-amber-100 text-amber-800 dark:bg-amber-950/50 dark:text-amber-400">
                <AlertTriangle className="size-5" />
              </span>
              <div>
                <h3 className="font-display text-base font-bold text-ink">
                  {t("modal.passwordAlertTitle")}
                </h3>
                <p className="text-xs text-ink-muted">
                  {t("modal.passwordAlertBody")}
                </p>
              </div>
            </div>

            <div className="mt-4 rounded-xl border border-border bg-surface-subtle p-3.5 space-y-2">
              <div className="flex items-center justify-between text-xs text-ink-muted">
                <span>{t("modal.revealedStaff", { name: revealedPassword.staffName })}</span>
                <span>{t("modal.revealedPhone", { phone: revealedPassword.phone })}</span>
              </div>
              <div className="flex items-center justify-between rounded-lg border border-border bg-surface-card px-3 py-2">
                <code className="font-mono text-base font-bold text-accent">
                  {revealedPassword.password}
                </code>
                <button
                  type="button"
                  onClick={() => handleCopyPassword(revealedPassword.password)}
                  className="inline-flex items-center gap-1 rounded-md bg-accent/10 px-2 py-1 text-xs font-semibold text-accent transition-colors hover:bg-accent/20"
                >
                  {copied ? (
                    <>
                      <Check className="size-3.5 text-emerald-600" />
                      {t("modal.copied")}
                    </>
                  ) : (
                    <>
                      <Copy className="size-3.5" />
                      {t("modal.copyPassword")}
                    </>
                  )}
                </button>
              </div>
            </div>

            <div className="mt-5 flex justify-end">
              <button
                type="button"
                onClick={() => setRevealedPassword(null)}
                className="rounded-xl bg-accent px-5 py-2 text-sm font-semibold text-ink-inverse shadow-sm transition-all hover:bg-accent-hover"
              >
                {t("modal.done")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
