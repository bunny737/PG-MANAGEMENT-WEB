"use client";

import React, { useState, useEffect } from "react";
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
  LoaderCircle,
  AlertTriangle,
  X
} from "lucide-react";
import { useTranslations } from "next-intl";
import { getInitials } from "@/lib/utils";
import { getResident, updateResident, type Resident, ApiError } from "@/lib/api";
import { StatusPill, getStatusTone } from "@/components/shared/StatusPill";

export function ResidentProfile({ id }: { id: string }) {
  const t = useTranslations("residents.profile");
  const tCommon = useTranslations("common");
  const tStatus = useTranslations("status");
  const [resident, setResident] = useState<Resident | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");

  const [activeTab, setActiveTab] = useState<"overview" | "financials" | "documents" | "maintenance">(
    "overview"
  );
  const [actionAlert, setActionAlert] = useState<{ type: string; message: string } | null>(null);

  // Edit Modal State
  const [isEditing, setIsEditing] = useState(false);
  const [isUpdating, setIsUpdating] = useState(false);
  const [editForm, setEditForm] = useState({
    first_name: "",
    last_name: "",
    gender: "",
    phone: "",
    email: "",
    permanent_address: "",
    current_address: "",
    emergency_contact_name: "",
    emergency_contact_relation: "",
    emergency_contact_phone: "",
    aadhaar_number: "",
    pan_number: "",
    passport_number: "",
    employee_id: "",
    student_id: "",
  });
  const [formError, setFormError] = useState("");

  useEffect(() => {
    let cancelled = false;
    getResident(id)
      .then((data) => {
        if (cancelled) return;
        setResident(data);
        setIsLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        console.error(err);
        setError(err instanceof ApiError ? err.message : t("errLoadFailed"));
        setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [id, t]);

  const handleAction = async (type: "transfer" | "vacate" | "edit") => {
    if (type === "edit" && resident) {
      setEditForm({
        first_name: resident.first_name || "",
        last_name: resident.last_name || "",
        gender: resident.gender || "",
        phone: resident.phone || "",
        email: resident.email || "",
        permanent_address: resident.permanent_address || "",
        current_address: resident.current_address || "",
        emergency_contact_name: resident.emergency_contact_name || "",
        emergency_contact_relation: resident.emergency_contact_relation || "",
        emergency_contact_phone: resident.emergency_contact_phone || "",
        aadhaar_number: resident.aadhaar_number || "",
        pan_number: resident.pan_number || "",
        passport_number: resident.passport_number || "",
        employee_id: resident.employee_id || "",
        student_id: resident.student_id || "",
      });
      setFormError("");
      setIsEditing(true);
      return;
    }

    const msg =
      type === "transfer"
        ? "Room transfer request initiated."
        : "Vacate checkout procedure initialized.";
    setActionAlert({ type, message: msg });
    setTimeout(() => setActionAlert(null), 4000);
  };

  const handleEditSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsUpdating(true);
    setFormError("");

    try {
      const updated = await updateResident(id, editForm);
      setResident(updated);
      setIsEditing(false);
      setActionAlert({ type: "edit", message: t("editModal.updatedToast") });
      setTimeout(() => setActionAlert(null), 4000);
    } catch (err) {
      console.error(err);
      setFormError(err instanceof ApiError ? err.message : "Failed to update profile.");
    } finally {
      setIsUpdating(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-32 text-sm text-ink-muted">
        <LoaderCircle className="size-8 animate-spin text-accent" />
        <p className="font-semibold mt-2">{t("loading")}</p>
      </div>
    );
  }

  if (error || !resident) {
    return (
      <div className="space-y-4 max-w-md mx-auto py-16 text-center">
        <div className="flex size-14 items-center justify-center rounded-full bg-status-critical-soft text-status-critical border border-status-critical/10 mx-auto">
          <AlertTriangle className="size-6" />
        </div>
        <h3 className="text-lg font-bold text-ink">{t("errLoadFailed")}</h3>
        <p className="text-xs text-ink-muted leading-relaxed">{error || t("errLoadFailed")}</p>
        <button
          onClick={() => window.location.reload()}
          className="px-4 py-2 bg-surface-inverse text-ink-inverse text-xs font-semibold rounded-xl hover:opacity-90 transition-opacity cursor-pointer shadow-sm"
        >
          {t("retry")}
        </button>
      </div>
    );
  }

  const fullName = `${resident.first_name} ${resident.last_name}`.trim();
  const initials = getInitials(fullName);

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      {/* Toast Alert */}
      {actionAlert && (
        <div className="fixed bottom-5 right-5 z-50 flex items-center gap-3 rounded-xl border border-emerald-100 bg-emerald-50 p-4 text-emerald-800 shadow-xl animate-bounce max-w-sm">
          <CheckCircle className="size-5 text-emerald-600 shrink-0" />
          <div className="text-sm">
            <span className="font-semibold capitalize">{actionAlert.message}</span>
          </div>
        </div>
      )}

      {/* Header & Breadcrumbs */}
      <div className="flex flex-col gap-4 md:flex-row md:items-center justify-between">
        <div>
          {/* Breadcrumbs */}
          <nav aria-label="Breadcrumb" className="flex items-center text-xs text-ink-muted mb-2">
            <ol className="inline-flex items-center space-x-1">
              <li>
                <Link href="/residents" className="hover:text-accent font-medium transition-colors">
                  {tCommon("nav.residents")}
                </Link>
              </li>
              <li className="flex items-center">
                <ChevronRight className="size-3 text-ink-faint mx-1" />
                <span className="text-ink font-semibold">{fullName}</span>
              </li>
            </ol>
          </nav>
          <h1 className="text-2xl font-bold tracking-tight text-ink md:text-3xl font-display-lg">{t("title")}</h1>
          <p className="mt-1 text-sm text-ink-muted">
            {t("subtitle")}
          </p>
        </div>

        {/* Action Buttons Toolbar */}
        <div className="flex flex-wrap gap-2.5">
          <button
            onClick={() => handleAction("edit")}
            className="inline-flex items-center justify-center gap-2 rounded-xl border border-border bg-surface-card px-4 py-2.5 text-xs font-bold text-ink hover:bg-surface-page active:scale-[0.98] transition-all cursor-pointer shadow-sm"
          >
            <Edit className="size-3.5" />
            {t("editProfile")}
          </button>
          <button
            onClick={() => handleAction("transfer")}
            className="inline-flex items-center justify-center gap-2 rounded-xl border border-border bg-surface-card px-4 py-2.5 text-xs font-bold text-ink hover:bg-surface-page active:scale-[0.98] transition-all cursor-pointer shadow-sm"
          >
            <ArrowRightLeft className="size-3.5 text-accent" />
            {t("transferRoom")}
          </button>
          <button
            onClick={() => handleAction("vacate")}
            className="inline-flex items-center justify-center gap-2 rounded-xl border border-status-critical/30 bg-status-critical-soft px-4 py-2.5 text-xs font-bold text-status-critical hover:bg-status-critical hover:text-ink-inverse active:scale-[0.98] transition-all cursor-pointer shadow-sm"
          >
            <LogOut className="size-3.5" />
            {t("vacateResident")}
          </button>
        </div>
      </div>

      {/* Main Resident Summary Bento Header Card */}
      <div className="bg-surface-card border border-border rounded-2xl p-6 shadow-sm flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
        <div className="flex items-center gap-5">
          <div className="size-16 rounded-full bg-accent-soft text-accent border border-accent/20 flex items-center justify-center font-extrabold text-xl shadow-inner shrink-0">
            {initials}
          </div>
          <div className="space-y-1">
            <div className="flex items-center gap-3 flex-wrap">
              <h2 className="text-xl font-extrabold text-ink">{fullName}</h2>
              <StatusPill
                label={tStatus(resident.status as "inquiry" | "reserved" | "active" | "notice_period" | "vacated" | "absconded" | "blacklisted" | "inactive") ?? resident.status}
                tone={getStatusTone(resident.status)}
              />
            </div>
            <p className="text-xs text-ink-muted flex items-center gap-3 flex-wrap pt-0.5">
              <span className="flex items-center gap-1">
                <Building className="size-3.5 text-ink-faint" />
                {resident.unit || t("overview.unassigned")} ({resident.block || t("overview.mainBuilding")})
              </span>
              <span>·</span>
              <span className="flex items-center gap-1">
                <Phone className="size-3.5 text-ink-faint" />
                {resident.phone}
              </span>
              <span>·</span>
              <span className="flex items-center gap-1">
                <Mail className="size-3.5 text-ink-faint" />
                {resident.email}
              </span>
            </p>
          </div>
        </div>

        <div className="flex md:flex-col items-center md:items-end justify-between w-full md:w-auto border-t md:border-t-0 border-border pt-4 md:pt-0 text-xs text-ink-muted space-y-1">
          <span className="font-semibold text-ink">{t("overview.contractedRent")}</span>
          <span className="font-mono text-base font-extrabold text-accent">{t("financials.rentAmount")}: {tCommon("labels.rupeeSymbol")}{parseFloat(resident.rent ?? "0").toFixed(2)}</span>
          <span className="text-[10px] text-ink-faint">{t("overview.joiningDate")}: {resident.joining_date || resident.move_in_date || "--"}</span>
        </div>
      </div>

      {/* Navigation Tabs Bar */}
      <div className="flex border-b border-border bg-surface-card rounded-xl p-1 shadow-sm overflow-x-auto">
        {[
          { id: "overview", label: t("tabs.overview"), icon: UserCheck },
          { id: "financials", label: t("tabs.financials"), icon: CreditCard },
          { id: "documents", label: t("tabs.documents"), icon: FileText },
          { id: "maintenance", label: t("tabs.maintenance"), icon: Wrench },
        ].map((tab) => {
          const isActive = activeTab === tab.id;
          const Icon = tab.icon;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as typeof activeTab)}
              className={`flex flex-1 items-center justify-center gap-2 rounded-lg py-2.5 px-3 text-xs font-bold transition-all cursor-pointer whitespace-nowrap ${
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

      {/* Tab 1: Overview & Profile Information */}
      {activeTab === "overview" && (
        <div className="grid grid-cols-1 gap-6 md:grid-cols-12 items-start animate-fade-in">
          {/* Left Column: Personal & Contact Info */}
          <div className="md:col-span-7 space-y-6">
            <div className="bg-surface-card border border-border rounded-2xl p-5 shadow-sm space-y-4">
              <h3 className="text-xs font-bold uppercase tracking-wider text-ink-faint border-b border-border pb-2.5">
                {t("overview.personalInfo")}
              </h3>
              <div className="grid grid-cols-2 gap-4 text-xs">
                <div>
                  <span className="text-ink-muted">{t("overview.gender")}</span>
                  <p className="font-semibold text-ink capitalize mt-0.5">{resident.gender || "--"}</p>
                </div>
                <div>
                  <span className="text-ink-muted">{t("overview.joiningDate")}</span>
                  <p className="font-semibold text-ink mt-0.5">{resident.joining_date || resident.move_in_date || "--"}</p>
                </div>
                <div className="col-span-2">
                  <span className="text-ink-muted">{t("overview.permanentAddress")}</span>
                  <p className="font-semibold text-ink mt-0.5 leading-relaxed">{resident.permanent_address || "--"}</p>
                </div>
                <div className="col-span-2">
                  <span className="text-ink-muted">{t("overview.currentAddress")}</span>
                  <p className="font-semibold text-ink mt-0.5 leading-relaxed">{resident.current_address || "--"}</p>
                </div>
              </div>
            </div>

            {/* Emergency Contact */}
            <div className="bg-surface-card border border-border rounded-2xl p-5 shadow-sm space-y-4">
              <h3 className="text-xs font-bold uppercase tracking-wider text-ink-faint border-b border-border pb-2.5">
                {t("overview.emergencyContact")}
              </h3>
              <div className="grid grid-cols-3 gap-4 text-xs">
                <div>
                  <span className="text-ink-muted">{t("overview.emergencyName")}</span>
                  <p className="font-semibold text-ink mt-0.5">{resident.emergency_contact_name || "--"}</p>
                </div>
                <div>
                  <span className="text-ink-muted">{t("overview.emergencyRelation")}</span>
                  <p className="font-semibold text-ink mt-0.5 capitalize">{resident.emergency_contact_relation || "--"}</p>
                </div>
                <div>
                  <span className="text-ink-muted">{t("overview.emergencyPhone")}</span>
                  <p className="font-mono font-semibold text-ink mt-0.5">{resident.emergency_contact_phone || "--"}</p>
                </div>
              </div>
            </div>
          </div>

          {/* Right Column: Identification & Room Details */}
          <div className="md:col-span-5 space-y-6">
            {/* Room Allocation */}
            <div className="bg-surface-card border border-border rounded-2xl p-5 shadow-sm space-y-4">
              <h3 className="text-xs font-bold uppercase tracking-wider text-ink-faint border-b border-border pb-2.5">
                {t("overview.roomAllocation")}
              </h3>
              <div className="space-y-3 text-xs">
                <div className="flex justify-between items-center pb-2 border-b border-border/40">
                  <span className="text-ink-muted">{t("overview.roomBed")}</span>
                  <span className="font-semibold text-ink">{resident.unit || t("overview.unassigned")}</span>
                </div>
                <div className="flex justify-between items-center pb-2 border-b border-border/40">
                  <span className="text-ink-muted">{t("overview.propertyBuilding")}</span>
                  <span className="font-semibold text-ink">{resident.block || t("overview.mainBuilding")}</span>
                </div>
                <div className="flex justify-between items-center pb-2 border-b border-border/40">
                  <span className="text-ink-muted">{t("overview.securityDeposit")}</span>
                  <span className="font-mono font-semibold text-ink">{tCommon("labels.rupeeSymbol")}{parseFloat(resident.deposit ?? "0").toFixed(2)}</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-ink-muted">{t("overview.rentType")}</span>
                  <span className="font-semibold text-ink">
                    {resident.rent_type === "with_food" ? t("overview.withFood") : t("overview.withoutFood")}
                  </span>
                </div>
              </div>
            </div>

            {/* IDs & Org */}
            <div className="bg-surface-card border border-border rounded-2xl p-5 shadow-sm space-y-4">
              <h3 className="text-xs font-bold uppercase tracking-wider text-ink-faint border-b border-border pb-2.5">
                {t("overview.identification")}
              </h3>
              <div className="space-y-3 text-xs">
                <div className="flex justify-between items-center pb-2 border-b border-border/40">
                  <span className="text-ink-muted">{t("overview.aadhaar")}</span>
                  <span className="font-mono font-semibold text-ink">{resident.aadhaar_number || "--"}</span>
                </div>
                <div className="flex justify-between items-center pb-2 border-b border-border/40">
                  <span className="text-ink-muted">{t("overview.pan")}</span>
                  <span className="font-mono font-semibold text-ink">{resident.pan_number || "--"}</span>
                </div>
                <div className="flex justify-between items-center pb-2 border-b border-border/40">
                  <span className="text-ink-muted">{t("overview.passport")}</span>
                  <span className="font-mono font-semibold text-ink">{resident.passport_number || "--"}</span>
                </div>
                <div className="flex justify-between items-center pb-2 border-b border-border/40">
                  <span className="text-ink-muted">{t("overview.employeeId")}</span>
                  <span className="font-mono font-semibold text-ink">{resident.employee_id || "--"}</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-ink-muted">{t("overview.studentId")}</span>
                  <span className="font-mono font-semibold text-ink">{resident.student_id || "--"}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Tab 2: Financials & Rent History */}
      {activeTab === "financials" && (
        <div className="bg-surface-card border border-border rounded-2xl p-5 shadow-sm space-y-4 animate-fade-in">
          <h3 className="text-xs font-bold uppercase tracking-wider text-ink-faint border-b border-border pb-3">
            {t("financials.heading")}
          </h3>
          <div className="overflow-x-auto text-xs">
            {resident.invoices && resident.invoices.length > 0 ? (
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-surface-page font-semibold text-ink-muted border-b border-border">
                    <th className="px-4 py-2.5">{t("financials.tableInvoice")}</th>
                    <th className="px-4 py-2.5">{t("financials.tablePeriod")}</th>
                    <th className="px-4 py-2.5">{t("financials.tableAmount")}</th>
                    <th className="px-4 py-2.5">{t("financials.tableStatus")}</th>
                    <th className="px-4 py-2.5 text-right">{t("financials.tablePaymentMode")}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border text-ink">
                  {resident.invoices.map((inv) => (
                    <tr key={inv.id} className="hover:bg-surface-page/35">
                      <td className="px-4 py-3 font-mono font-semibold text-accent">{inv.invoice_number || inv.id}</td>
                      <td className="px-4 py-3 text-ink-muted">{inv.billing_period_start} - {inv.billing_period_end}</td>
                      <td className="px-4 py-3 font-mono font-semibold">{tCommon("labels.rupeeSymbol")}{parseFloat(inv.total_amount ?? "0").toFixed(2)}</td>
                      <td className="px-4 py-3">
                        <StatusPill
                          label={tStatus(inv.status as "draft" | "issued" | "paid" | "partially_paid" | "void") ?? inv.status}
                          tone={getStatusTone(inv.status)}
                        />
                      </td>
                      <td className="px-4 py-3 text-right uppercase text-[10px] font-bold text-ink-muted">
                        {inv.payment_mode || t("financials.onlineMode")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="p-8 text-center text-ink-muted">
                {t("financials.noInvoices")}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Tab 3: Documents & KYC */}
      {activeTab === "documents" && (
        <div className="bg-surface-card border border-border rounded-2xl p-5 shadow-sm space-y-4 animate-fade-in">
          <div className="flex justify-between items-center border-b border-border pb-3">
            <h3 className="text-xs font-bold uppercase tracking-wider text-ink-faint">{t("documents.heading")}</h3>
            <button className="rounded-xl bg-accent hover:bg-accent-hover text-ink-inverse text-xs font-semibold px-3 py-1.5 transition-colors cursor-pointer inline-flex items-center gap-1.5">
              <FileCheck2 className="size-3.5" />
              {t("documents.uploadNew")}
            </button>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
            <div className="border border-border rounded-xl p-4 bg-surface-page/40 space-y-2 flex flex-col justify-between">
              <div className="flex items-start justify-between">
                <div className="space-y-0.5">
                  <h4 className="font-bold text-ink">{t("documents.idProof")}</h4>
                  <p className="text-[10px] text-ink-muted">{t("overview.aadhaar")}: {resident.aadhaar_number || t("documents.uploaded")}</p>
                </div>
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-100 text-[9px] font-bold">
                  <CheckCircle className="size-3" /> {t("documents.verified")}
                </span>
              </div>
              <button className="text-accent text-[11px] font-bold hover:underline self-start cursor-pointer pt-2">
                {t("documents.download")} ›
              </button>
            </div>

            <div className="border border-border rounded-xl p-4 bg-surface-page/40 space-y-2 flex flex-col justify-between">
              <div className="flex items-start justify-between">
                <div className="space-y-0.5">
                  <h4 className="font-bold text-ink">{t("documents.leaseContract")}</h4>
                  <p className="text-[10px] text-ink-muted">{t("documents.signedOn", { date: resident.joining_date || resident.move_in_date || "--" })}</p>
                </div>
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-100 text-[9px] font-bold">
                  <CheckCircle className="size-3" /> {t("documents.verified")}
                </span>
              </div>
              <button className="text-accent text-[11px] font-bold hover:underline self-start cursor-pointer pt-2">
                {t("documents.download")} ›
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Tab 4: Complaints & Service Tickets */}
      {activeTab === "maintenance" && (
        <div className="bg-surface-card border border-border rounded-2xl p-5 shadow-sm space-y-4 animate-fade-in">
          <h3 className="text-xs font-bold uppercase tracking-wider text-ink-faint border-b border-border pb-3">
            {t("maintenance.heading")}
          </h3>
          <div className="overflow-x-auto text-xs">
            {resident.complaints && resident.complaints.length > 0 ? (
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-surface-page font-semibold text-ink-muted border-b border-border">
                    <th className="px-4 py-2.5">{t("maintenance.ticket")}</th>
                    <th className="px-4 py-2.5">{t("maintenance.title")}</th>
                    <th className="px-4 py-2.5">{t("maintenance.category")}</th>
                    <th className="px-4 py-2.5">{t("maintenance.status")}</th>
                    <th className="px-4 py-2.5 text-right">{t("maintenance.loggedOn")}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border text-ink">
                  {resident.complaints.map((c) => (
                    <tr key={c.id} className="hover:bg-surface-page/35">
                      <td className="px-4 py-3 font-mono font-semibold text-accent">#{c.id.substring(0, 6)}</td>
                      <td className="px-4 py-3 font-semibold">{c.description}</td>
                      <td className="px-4 py-3 capitalize text-ink-muted">{c.category}</td>
                      <td className="px-4 py-3">
                        <StatusPill
                          label={tStatus(c.status as "open" | "assigned" | "in_progress" | "resolved" | "closed") ?? c.status}
                          tone={getStatusTone(c.status)}
                        />
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-ink-muted">{c.created_at?.split("T")[0]}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="p-8 text-center text-ink-muted">
                {t("maintenance.noComplaints")}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Edit Resident Profile Modal */}
      {isEditing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-on-surface/40 backdrop-blur-sm animate-fade-in">
          <div className="bg-surface-card border border-border rounded-2xl max-w-2xl w-full p-6 shadow-2xl space-y-4 max-h-[90vh] overflow-y-auto">
            <div className="flex justify-between items-center border-b border-border pb-3">
              <div>
                <h3 className="text-base font-bold text-ink">{t("editModal.title")}</h3>
                <p className="text-xs text-ink-muted mt-0.5">{t("editModal.subtitle")}</p>
              </div>
              <button
                onClick={() => setIsEditing(false)}
                className="p-1 rounded-lg text-ink-muted hover:bg-surface-page transition-colors cursor-pointer"
              >
                <X className="size-5" />
              </button>
            </div>

            {formError && (
              <div className="p-3 rounded-xl bg-status-critical-soft border border-status-critical/20 text-status-critical text-xs font-semibold">
                {formError}
              </div>
            )}

            <form onSubmit={handleEditSubmit} className="space-y-4 text-xs">
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1">
                  <label className="font-semibold text-ink-muted">{t("editModal.firstName")}</label>
                  <input
                    type="text"
                    value={editForm.first_name}
                    onChange={(e) => setEditForm({ ...editForm, first_name: e.target.value })}
                    className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2 text-ink outline-none focus:ring-2 focus:ring-accent"
                  />
                </div>
                <div className="space-y-1">
                  <label className="font-semibold text-ink-muted">{t("editModal.lastName")}</label>
                  <input
                    type="text"
                    value={editForm.last_name}
                    onChange={(e) => setEditForm({ ...editForm, last_name: e.target.value })}
                    className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2 text-ink outline-none focus:ring-2 focus:ring-accent"
                  />
                </div>
                <div className="space-y-1">
                  <label className="font-semibold text-ink-muted">{t("editModal.phone")}</label>
                  <input
                    type="text"
                    value={editForm.phone}
                    onChange={(e) => setEditForm({ ...editForm, phone: e.target.value })}
                    className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2 text-ink outline-none focus:ring-2 focus:ring-accent"
                  />
                </div>
                <div className="space-y-1">
                  <label className="font-semibold text-ink-muted">{t("editModal.email")}</label>
                  <input
                    type="email"
                    value={editForm.email}
                    onChange={(e) => setEditForm({ ...editForm, email: e.target.value })}
                    className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2 text-ink outline-none focus:ring-2 focus:ring-accent"
                  />
                </div>
                <div className="col-span-2 space-y-1">
                  <label className="font-semibold text-ink-muted">{t("editModal.permAddress")}</label>
                  <input
                    type="text"
                    value={editForm.permanent_address}
                    onChange={(e) => setEditForm({ ...editForm, permanent_address: e.target.value })}
                    className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2 text-ink outline-none focus:ring-2 focus:ring-accent"
                  />
                </div>
                <div className="space-y-1">
                  <label className="font-semibold text-ink-muted">{t("editModal.aadhaar")}</label>
                  <input
                    type="text"
                    value={editForm.aadhaar_number}
                    onChange={(e) => setEditForm({ ...editForm, aadhaar_number: e.target.value })}
                    className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2 text-ink outline-none focus:ring-2 focus:ring-accent"
                  />
                </div>
                <div className="space-y-1">
                  <label className="font-semibold text-ink-muted">{t("editModal.pan")}</label>
                  <input
                    type="text"
                    value={editForm.pan_number}
                    onChange={(e) => setEditForm({ ...editForm, pan_number: e.target.value })}
                    className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2 text-ink outline-none focus:ring-2 focus:ring-accent"
                  />
                </div>
              </div>

              <div className="flex justify-end gap-3 pt-3 border-t border-border">
                <button
                  type="button"
                  onClick={() => setIsEditing(false)}
                  className="px-4 py-2 rounded-xl border border-border bg-surface-page font-bold text-ink-muted hover:bg-surface-card cursor-pointer"
                >
                  {t("editModal.cancel")}
                </button>
                <button
                  type="submit"
                  disabled={isUpdating}
                  className="px-4 py-2 rounded-xl bg-accent text-ink-inverse font-bold hover:bg-accent-hover transition-colors cursor-pointer disabled:opacity-50"
                >
                  {isUpdating ? t("editModal.saving") : t("editModal.save")}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
