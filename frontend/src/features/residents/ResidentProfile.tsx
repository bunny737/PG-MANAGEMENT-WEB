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
  Clock,
  LoaderCircle,
  AlertTriangle,
  X
} from "lucide-react";
import { getInitials } from "@/lib/utils";
import { getResident, updateResident, type Resident, ApiError } from "@/lib/api";

export function ResidentProfile({ id }: { id: string }) {
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
        setError(err instanceof ApiError ? err.message : "Failed to load resident profile.");
        setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

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

    let msg = "";
    if (type === "transfer") {
      msg = `Transfer workflow triggered for ${resident?.first_name}. Opening room allocator shortly.`;
    } else if (type === "vacate") {
      msg = `Notice exit checklist wizard initiated for ${resident?.first_name}. Opening exits workflow shortly.`;
    }
    setActionAlert({ type, message: msg });
    setTimeout(() => setActionAlert(null), 5000);
  };

  const handleEditSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editForm.first_name) {
      setFormError("First Name is required.");
      return;
    }
    if (!editForm.phone) {
      setFormError("Phone number is required.");
      return;
    }

    setIsUpdating(true);
    setFormError("");
    try {
      const updated = await updateResident(id, editForm);
      setResident(updated);
      setIsEditing(false);
      setActionAlert({ type: "edit", message: "Resident profile updated successfully." });
      setTimeout(() => setActionAlert(null), 4000);
    } catch (err) {
      console.error(err);
      setFormError(err instanceof ApiError ? err.message : "Failed to update profile. Please try again.");
    } finally {
      setIsUpdating(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-32 text-sm text-ink-muted">
        <LoaderCircle className="size-8 animate-spin text-accent" />
        <p className="font-semibold mt-2">Loading resident profile...</p>
      </div>
    );
  }

  if (error || !resident) {
    return (
      <div className="space-y-4 max-w-md mx-auto py-16 text-center">
        <div className="flex size-14 items-center justify-center rounded-full bg-status-critical-soft text-status-critical border border-status-critical/10 mx-auto">
          <AlertTriangle className="size-6" />
        </div>
        <h3 className="text-lg font-bold text-ink">Failed to Load Profile</h3>
        <p className="text-xs text-ink-muted leading-relaxed">
          {error || "Could not retrieve resident data."}
        </p>
        <Link
          href="/residents"
          className="inline-flex px-4 py-2 bg-surface-inverse text-ink-inverse text-xs font-semibold rounded-xl hover:opacity-90 transition-opacity cursor-pointer shadow-sm"
        >
          Back to Directory
        </Link>
      </div>
    );
  }

  const fullName = `${resident.first_name} ${resident.last_name}`.trim();

  return (
    <div className="space-y-6">
      {/* Action Notification Toast */}
      {actionAlert && (
        <div className="fixed bottom-5 right-5 z-50 flex items-center gap-3 rounded-xl border border-emerald-100 bg-emerald-50 p-4 text-emerald-800 shadow-xl animate-bounce max-w-sm">
          <CheckCircle className="size-5 text-emerald-600 shrink-0" />
          <div className="text-sm">
            <span className="font-semibold capitalize">{actionAlert.type} Success</span>
            <p className="text-xs text-emerald-700 mt-0.5">{actionAlert.message}</p>
          </div>
        </div>
      )}

      {/* Edit Profile Modal Dialog */}
      {isEditing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-on-surface/40 backdrop-blur-sm transition-opacity">
          <div className="bg-surface-card border border-border rounded-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto shadow-2xl animate-fade-in flex flex-col">
            {/* Modal Header */}
            <div className="px-6 py-4.5 border-b border-border flex items-center justify-between">
              <h3 className="text-sm font-bold uppercase tracking-wider text-ink">Edit Resident Profile</h3>
              <button
                onClick={() => setIsEditing(false)}
                className="p-1 text-ink-muted hover:text-ink hover:bg-surface-page rounded-lg transition-colors cursor-pointer"
              >
                <X className="size-5" />
              </button>
            </div>

            {/* Modal Form */}
            <form onSubmit={handleEditSubmit} className="p-6 space-y-5 flex-1">
              {formError && (
                <div className="rounded-xl border border-status-critical/15 bg-status-critical-soft p-3 text-xs text-status-critical">
                  {formError}
                </div>
              )}

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                {/* First Name */}
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                    First Name <span className="text-status-critical">*</span>
                  </label>
                  <input
                    type="text"
                    value={editForm.first_name}
                    onChange={(e) => setEditForm({ ...editForm, first_name: e.target.value })}
                    className="w-full rounded-xl border border-border bg-surface-page px-3.5 py-2 text-sm text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent"
                    required
                  />
                </div>

                {/* Last Name */}
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                    Last Name
                  </label>
                  <input
                    type="text"
                    value={editForm.last_name}
                    onChange={(e) => setEditForm({ ...editForm, last_name: e.target.value })}
                    className="w-full rounded-xl border border-border bg-surface-page px-3.5 py-2 text-sm text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent"
                  />
                </div>

                {/* Gender */}
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                    Gender
                  </label>
                  <select
                    value={editForm.gender}
                    onChange={(e) => setEditForm({ ...editForm, gender: e.target.value })}
                    className="w-full rounded-xl border border-border bg-surface-page px-3.5 py-2 text-sm text-ink-muted outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent"
                  >
                    <option value="">Select Gender</option>
                    <option value="male">Male</option>
                    <option value="female">Female</option>
                    <option value="other">Other</option>
                  </select>
                </div>

                {/* Phone */}
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                    Phone <span className="text-status-critical">*</span>
                  </label>
                  <input
                    type="text"
                    value={editForm.phone}
                    onChange={(e) => setEditForm({ ...editForm, phone: e.target.value })}
                    className="w-full rounded-xl border border-border bg-surface-page px-3.5 py-2 text-sm text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent"
                    required
                  />
                </div>

                {/* Email */}
                <div className="space-y-1.5 sm:col-span-2">
                  <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                    Email Address
                  </label>
                  <input
                    type="email"
                    value={editForm.email}
                    onChange={(e) => setEditForm({ ...editForm, email: e.target.value })}
                    className="w-full rounded-xl border border-border bg-surface-page px-3.5 py-2 text-sm text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent"
                  />
                </div>

                {/* Current Address */}
                <div className="space-y-1.5 sm:col-span-2">
                  <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                    Current Address
                  </label>
                  <textarea
                    value={editForm.current_address}
                    onChange={(e) => setEditForm({ ...editForm, current_address: e.target.value })}
                    rows={2}
                    className="w-full rounded-xl border border-border bg-surface-page px-3.5 py-2 text-sm text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent resize-none"
                  />
                </div>

                {/* Permanent Address */}
                <div className="space-y-1.5 sm:col-span-2">
                  <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                    Permanent Address
                  </label>
                  <textarea
                    value={editForm.permanent_address}
                    onChange={(e) => setEditForm({ ...editForm, permanent_address: e.target.value })}
                    rows={2}
                    className="w-full rounded-xl border border-border bg-surface-page px-3.5 py-2 text-sm text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent resize-none"
                  />
                </div>

                {/* Section Divider */}
                <div className="sm:col-span-2 border-t border-border pt-4">
                  <h4 className="text-xs font-bold text-ink uppercase tracking-wider mb-3">Emergency Contact Details</h4>
                </div>

                {/* Emergency Contact Name */}
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                    Guardian Name
                  </label>
                  <input
                    type="text"
                    value={editForm.emergency_contact_name}
                    onChange={(e) => setEditForm({ ...editForm, emergency_contact_name: e.target.value })}
                    className="w-full rounded-xl border border-border bg-surface-page px-3.5 py-2 text-sm text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent"
                  />
                </div>

                {/* Relation */}
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                    Relation
                  </label>
                  <input
                    type="text"
                    value={editForm.emergency_contact_relation}
                    onChange={(e) => setEditForm({ ...editForm, emergency_contact_relation: e.target.value })}
                    className="w-full rounded-xl border border-border bg-surface-page px-3.5 py-2 text-sm text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent"
                  />
                </div>

                {/* Emergency Phone */}
                <div className="space-y-1.5 sm:col-span-2">
                  <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                    Guardian Phone
                  </label>
                  <input
                    type="text"
                    value={editForm.emergency_contact_phone}
                    onChange={(e) => setEditForm({ ...editForm, emergency_contact_phone: e.target.value })}
                    className="w-full rounded-xl border border-border bg-surface-page px-3.5 py-2 text-sm text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent"
                  />
                </div>

                {/* Section Divider */}
                <div className="sm:col-span-2 border-t border-border pt-4">
                  <h4 className="text-xs font-bold text-ink uppercase tracking-wider mb-3">Identity Documents Information</h4>
                </div>

                {/* Aadhaar Number */}
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                    Aadhaar Number
                  </label>
                  <input
                    type="text"
                    value={editForm.aadhaar_number}
                    onChange={(e) => setEditForm({ ...editForm, aadhaar_number: e.target.value })}
                    className="w-full rounded-xl border border-border bg-surface-page px-3.5 py-2 text-sm text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent font-mono"
                  />
                </div>

                {/* PAN Number */}
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                    PAN Number
                  </label>
                  <input
                    type="text"
                    value={editForm.pan_number}
                    onChange={(e) => setEditForm({ ...editForm, pan_number: e.target.value })}
                    className="w-full rounded-xl border border-border bg-surface-page px-3.5 py-2 text-sm text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent font-mono"
                  />
                </div>

                {/* Passport Number */}
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                    Passport Number
                  </label>
                  <input
                    type="text"
                    value={editForm.passport_number}
                    onChange={(e) => setEditForm({ ...editForm, passport_number: e.target.value })}
                    className="w-full rounded-xl border border-border bg-surface-page px-3.5 py-2 text-sm text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent font-mono"
                  />
                </div>

                {/* Employee ID */}
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                    Employee ID
                  </label>
                  <input
                    type="text"
                    value={editForm.employee_id}
                    onChange={(e) => setEditForm({ ...editForm, employee_id: e.target.value })}
                    className="w-full rounded-xl border border-border bg-surface-page px-3.5 py-2 text-sm text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent font-mono"
                  />
                </div>

                {/* Student ID */}
                <div className="space-y-1.5 sm:col-span-2">
                  <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                    Student ID
                  </label>
                  <input
                    type="text"
                    value={editForm.student_id}
                    onChange={(e) => setEditForm({ ...editForm, student_id: e.target.value })}
                    className="w-full rounded-xl border border-border bg-surface-page px-3.5 py-2 text-sm text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent font-mono"
                  />
                </div>
              </div>

              {/* Action Buttons */}
              <div className="flex justify-end gap-3 pt-4 border-t border-border">
                <button
                  type="button"
                  onClick={() => setIsEditing(false)}
                  disabled={isUpdating}
                  className="rounded-xl border border-border bg-surface-page px-4 py-2.5 text-xs font-bold text-ink hover:bg-surface-card cursor-pointer transition-colors disabled:opacity-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isUpdating}
                  className="rounded-xl bg-accent px-5 py-2.5 text-xs font-bold text-ink-inverse hover:bg-accent-hover transition-colors cursor-pointer disabled:opacity-50 flex items-center justify-center gap-1.5"
                >
                  {isUpdating && <LoaderCircle className="size-3.5 animate-spin" />}
                  Save Changes
                </button>
              </div>
            </form>
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
                <span className="text-ink font-semibold">{fullName}</span>
              </li>
            </ol>
          </nav>

          {/* Profile Name & Status Badge */}
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-bold tracking-tight text-ink md:text-3xl">{fullName}</h1>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface-card px-3 py-1 text-xs font-semibold text-ink">
              <span
                className={`size-2 rounded-full ${
                  resident.status === "active"
                    ? "bg-emerald-500"
                    : resident.status === "notice_period"
                    ? "bg-red-500"
                    : resident.status === "reserved"
                    ? "bg-amber-500"
                    : resident.status === "inquiry"
                    ? "bg-indigo-500"
                    : "bg-slate-400"
                }`}
              />
              {resident.status === "active" && "Active"}
              {resident.status === "notice_period" && "Notice Period"}
              {resident.status === "reserved" && "Reserved"}
              {resident.status === "inquiry" && "Inquiry"}
              {resident.status === "inactive" && "Inactive"}
              {resident.status === "vacated" && "Vacated"}
              {resident.status === "absconded" && "Absconded"}
              {resident.status === "blacklisted" && "Blacklisted"}
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
            <div className="size-24 rounded-full border border-border flex items-center justify-center font-bold text-3xl mb-4 bg-slate-100 text-slate-800 shadow-inner">
              {getInitials(fullName)}
            </div>

            <h2 className="text-lg font-bold text-ink">{fullName}</h2>
            <p className="text-xs text-ink-muted mt-0.5">
              Resident ID: <span className="font-mono font-medium">{`RSD-${resident.id.slice(0, 8)}`}</span>
            </p>

            {/* Quick specifications card */}
            <div className="w-full mt-5 rounded-xl bg-surface-page p-3 border border-border/60 text-left text-xs space-y-2.5">
              <div className="flex justify-between items-center">
                <span className="text-ink-muted">Unit / Room</span>
                <span className="font-semibold text-ink">{resident.unit || "Not Allocated"}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-ink-muted">Building Block</span>
                <span className="font-semibold text-ink">{resident.block ? `Block ${resident.block}` : "N/A"}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-ink-muted">Joined Date</span>
                <span className="font-semibold text-ink">{resident.move_in_date || "N/A"}</span>
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
                <span className="text-ink truncate">{resident.email || "--"}</span>
              </li>
              <li className="flex items-center gap-3">
                <Phone className="size-4 text-ink-muted shrink-0" />
                <span className="font-mono text-ink">{resident.phone || "--"}</span>
              </li>
              {resident.emergency_contact_name && (
                <li className="flex flex-col gap-1.5 pt-3.5 border-t border-border">
                  <div className="flex items-center gap-2 text-xs font-bold text-ink-muted">
                    <UserCheck className="size-3.5" />
                    Emergency Contact
                  </div>
                  <div className="text-xs pl-5.5 space-y-0.5">
                    <p className="font-semibold text-ink">
                      {resident.emergency_contact_name}{" "}
                      {resident.emergency_contact_relation && `(${resident.emergency_contact_relation})`}
                    </p>
                    <p className="font-mono text-ink-muted">{resident.emergency_contact_phone || "No phone"}</p>
                  </div>
                </li>
              )}
            </ul>
          </div>
        </div>

        {/* Right Column: Dynamic Tabs Navigation */}
        <div className="lg:col-span-8 space-y-6">
          {/* Tabs Menu selectors */}
          <div className="flex gap-2.5 overflow-x-auto border-b border-border pb-1">
            {[
              { id: "overview", label: "Lease Overview", icon: Building },
              { id: "financials", label: "Financials", icon: CreditCard },
              { id: "documents", label: "Documents", icon: FileText },
              { id: "maintenance", label: "Maintenance", icon: Wrench },
            ].map((tab) => {
              const active = activeTab === tab.id;
              const Icon = tab.icon;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id as "overview" | "financials" | "documents" | "maintenance")}
                  className={`flex items-center gap-2 border-b-2 px-3 py-2 text-xs font-bold whitespace-nowrap transition-colors cursor-pointer ${
                    active
                      ? "border-accent text-accent"
                      : "border-transparent text-ink-muted hover:text-ink"
                  }`}
                >
                  <Icon className="size-3.5 shrink-0" />
                  {tab.label}
                </button>
              );
            })}
          </div>

          {/* Overview Tab Content */}
          {activeTab === "overview" && (
            <div className="space-y-6 animate-fade-in">
              {/* Identity details list */}
              <div className="rounded-2xl border border-border bg-surface-card p-5 shadow-sm space-y-4">
                <h3 className="text-xs font-bold uppercase tracking-wider text-ink-faint">KYC / Identity Verified Details</h3>
                <div className="grid grid-cols-2 gap-y-4 gap-x-2 text-xs">
                  <div>
                    <p className="text-ink-muted mb-0.5">Aadhaar Number</p>
                    <p className="font-mono font-semibold text-ink">{resident.aadhaar_number || "--"}</p>
                  </div>
                  <div>
                    <p className="text-ink-muted mb-0.5">PAN Card Number</p>
                    <p className="font-mono font-semibold text-ink">{resident.pan_number || "--"}</p>
                  </div>
                  <div>
                    <p className="text-ink-muted mb-0.5">Passport Number</p>
                    <p className="font-mono font-semibold text-ink">{resident.passport_number || "--"}</p>
                  </div>
                  <div>
                    <p className="text-ink-muted mb-0.5">Gender / Gender Info</p>
                    <p className="font-semibold text-ink capitalize">{resident.gender || "--"}</p>
                  </div>
                  {resident.employee_id && (
                    <div>
                      <p className="text-ink-muted mb-0.5">Employee ID</p>
                      <p className="font-mono font-semibold text-ink">{resident.employee_id}</p>
                    </div>
                  )}
                  {resident.student_id && (
                    <div>
                      <p className="text-ink-muted mb-0.5">Student ID</p>
                      <p className="font-mono font-semibold text-ink">{resident.student_id}</p>
                    </div>
                  )}
                </div>
              </div>

              {/* Recent Activity Timeline card */}
              <div className="rounded-2xl border border-border bg-surface-card p-5 shadow-sm">
                <div className="flex justify-between items-center mb-5">
                  <h3 className="text-sm font-bold uppercase tracking-wider text-ink">Recent Activity</h3>
                </div>
                {/* Timeline */}
                <div className="relative border-l border-border ml-3 pl-6 flex flex-col gap-6.5 py-1">
                  <div className="relative">
                    <span className="absolute -left-[30px] top-1.5 flex size-3 items-center justify-center rounded-full bg-accent ring-4 ring-surface-card">
                      <span className="size-1 rounded-full bg-ink-inverse" />
                    </span>
                    <div className="flex flex-col">
                      <span className="text-sm font-semibold text-ink">Resident Onboarded</span>
                      <span className="text-xs text-ink-muted mt-0.5">Created profile status set to {resident.status}.</span>
                      <span className="flex items-center gap-1 text-[10px] text-ink-faint font-mono mt-1">
                        <Clock className="size-3" /> Registered on {new Date(resident.created_at).toLocaleDateString()}
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
              <div className="p-8 text-center text-ink-muted text-xs">
                No financial invoices registered yet for this tenant lease contract.
              </div>
            </div>
          )}

          {/* Documents Tab Content */}
          {activeTab === "documents" && (
            <div className="rounded-2xl border border-border bg-surface-card p-5 shadow-sm space-y-4 animate-fade-in">
              <h3 className="text-sm font-bold uppercase tracking-wider text-ink border-b border-border pb-3">Stored Documents</h3>
              <div className="space-y-3">
                {resident.aadhaar_number && (
                  <div className="flex items-center justify-between border border-border rounded-xl p-3.5 hover:bg-surface-page/20 transition-colors">
                    <div className="flex items-center gap-3">
                      <div className="flex size-9 items-center justify-center rounded-lg bg-blue-50 text-blue-600 border border-blue-100">
                        <FileCheck2 className="size-5" />
                      </div>
                      <div>
                        <h4 className="text-xs font-semibold text-ink">National_ID_Aadhaar.pdf</h4>
                        <p className="text-[10px] text-ink-muted">Aadhaar verified: {resident.aadhaar_number}</p>
                      </div>
                    </div>
                  </div>
                )}
                {resident.pan_number && (
                  <div className="flex items-center justify-between border border-border rounded-xl p-3.5 hover:bg-surface-page/20 transition-colors">
                    <div className="flex items-center gap-3">
                      <div className="flex size-9 items-center justify-center rounded-lg bg-slate-50 text-slate-600 border border-slate-200">
                        <FileText className="size-5" />
                      </div>
                      <div>
                        <h4 className="text-xs font-semibold text-ink">Tax_ID_PAN.pdf</h4>
                        <p className="text-[10px] text-ink-muted">PAN verified: {resident.pan_number}</p>
                      </div>
                    </div>
                  </div>
                )}
                {!resident.aadhaar_number && !resident.pan_number && (
                  <div className="p-8 text-center text-ink-muted text-xs">
                    No verified identity document details registered.
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Maintenance Tab Content */}
          {activeTab === "maintenance" && (
            <div className="rounded-2xl border border-border bg-surface-card p-5 shadow-sm space-y-4 animate-fade-in">
              <h3 className="text-sm font-bold uppercase tracking-wider text-ink border-b border-border pb-3">Maintenance Log</h3>
              <div className="p-8 text-center text-ink-muted text-xs">
                No active maintenance logs reported by this resident unit.
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
