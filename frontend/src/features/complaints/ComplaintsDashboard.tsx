"use client";

import React, { useState, useEffect, useMemo, useRef } from "react";
import {
  Search,
  Plus,
  LoaderCircle,
  AlertTriangle,
  X,
  Send,
  Wrench,
  ShieldAlert,
  AlertCircle
} from "lucide-react";
import { useTranslations } from "next-intl";
import {
  listComplaints,
  getComplaint,
  createComplaint,
  assignComplaint,
  updateComplaintStatus,
  createComplaintComment,
  listResidents,
  listStaff,
  getCurrentUser,
  type Complaint,
  type Resident,
  type StaffUser,
  ApiError
} from "@/lib/api";
import { StatusPill, getStatusTone } from "@/components/shared/StatusPill";

const CATEGORY_MAP: Record<string, { icon: React.ComponentType<{ className?: string }>; color: string }> = {
  electrical: { icon: Wrench, color: "text-amber-500 bg-amber-50 border-amber-100" },
  plumbing: { icon: Wrench, color: "text-blue-500 bg-blue-50 border-blue-100" },
  internet_wifi: { icon: Wrench, color: "text-indigo-500 bg-indigo-50 border-indigo-100" },
  housekeeping: { icon: Wrench, color: "text-teal-500 bg-teal-50 border-teal-100" },
  security: { icon: ShieldAlert, color: "text-rose-500 bg-rose-50 border-rose-100" },
  furniture: { icon: Wrench, color: "text-orange-500 bg-orange-50 border-orange-100" },
  other: { icon: AlertCircle, color: "text-slate-500 bg-slate-50 border-slate-100" }
};

const PRIORITY_MAP: Record<string, { color: string }> = {
  low: { color: "bg-slate-50 border-slate-200 text-slate-500" },
  medium: { color: "bg-sky-50 border-sky-100 text-sky-600" },
  high: { color: "bg-orange-50 border-orange-200 text-orange-600" },
  urgent: { color: "bg-rose-50 border-rose-200 text-rose-600 font-bold" }
};

export function ComplaintsDashboard() {
  const t = useTranslations("complaints");
  const tStatus = useTranslations("status");

  const [complaints, setComplaints] = useState<Complaint[]>([]);
  const [residents, setResidents] = useState<Resident[]>([]);
  const [staff, setStaff] = useState<StaffUser[]>([]);
  
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const [reloadTrigger, setReloadTrigger] = useState(0);

  // Filter States
  const [statusFilter, setStatusFilter] = useState("all");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [priorityFilter, setPriorityFilter] = useState("all");
  const [searchTerm, setSearchTerm] = useState("");

  // Modal / Detail States
  const [selectedComplaint, setSelectedComplaint] = useState<Complaint | null>(null);
  const [isLoggingNew, setIsLoggingNew] = useState(false);
  const [newCommentText, setNewCommentText] = useState("");
  const [isSubmittingComment, setIsSubmittingComment] = useState(false);

  // New Complaint Form
  const [formResident, setFormResident] = useState("");
  const [formCategory, setFormCategory] = useState("electrical");
  const [formPriority, setFormPriority] = useState("medium");
  const [formDescription, setFormDescription] = useState("");
  const [formFile, setFormFile] = useState<File | null>(null);
  const [formSubmitError, setFormSubmitError] = useState("");
  const [isSubmittingForm, setIsSubmittingForm] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;

    Promise.all([
      listComplaints(),
      listResidents(),
      listStaff(),
      getCurrentUser().catch(() => null)
    ])
      .then(([complaintData, residentData, staffData]) => {
        if (cancelled) return;
        setComplaints(complaintData);
        setResidents(residentData);
        setStaff(staffData);
        if (residentData.length > 0) setFormResident(residentData[0].id);
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
  }, [t, reloadTrigger]);

  const refreshData = () => {
    setIsLoading(true);
    setError("");
    setReloadTrigger((prev) => prev + 1);
  };

  // Filter complaints
  const filteredComplaints = useMemo(() => {
    return complaints.filter((c) => {
      const residentName = c.resident_details
        ? `${c.resident_details.first_name} ${c.resident_details.last_name}`
        : c.resident_name || "";
      const roomStr = c.resident_details?.unit || c.resident_room || "";
      const query = searchTerm.toLowerCase();

      const matchesSearch =
        c.id.toLowerCase().includes(query) ||
        c.description.toLowerCase().includes(query) ||
        residentName.toLowerCase().includes(query) ||
        roomStr.toLowerCase().includes(query);

      const matchesStatus = statusFilter === "all" ? true : c.status === statusFilter;
      const matchesCategory = categoryFilter === "all" ? true : c.category === categoryFilter;
      const matchesPriority = priorityFilter === "all" ? true : c.priority === priorityFilter;

      return matchesSearch && matchesStatus && matchesCategory && matchesPriority;
    });
  }, [complaints, searchTerm, statusFilter, categoryFilter, priorityFilter]);

  // Handle open complaint detail modal
  const handleOpenDetail = async (c: Complaint) => {
    setSelectedComplaint(c);
    try {
      const fresh = await getComplaint(c.id);
      setSelectedComplaint(fresh);
    } catch (err) {
      console.error("Failed to load fresh complaint details:", err);
    }
  };

  // Assign Staff
  const handleAssignStaff = async (assignedToId: string) => {
    if (!selectedComplaint) return;
    try {
      const updated = await assignComplaint(selectedComplaint.id, assignedToId);
      setSelectedComplaint(updated);
      setComplaints((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
    } catch (err) {
      console.error("Failed to assign staff:", err);
      alert(err instanceof ApiError ? err.message : "Failed to assign staff member");
    }
  };

  // Update Status
  const handleStatusChange = async (newStatus: string) => {
    if (!selectedComplaint) return;
    try {
      const updated = await updateComplaintStatus(selectedComplaint.id, newStatus);
      setSelectedComplaint(updated);
      setComplaints((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
    } catch (err) {
      console.error("Failed to update status:", err);
      alert(err instanceof ApiError ? err.message : "Failed to update complaint status");
    }
  };

  // Post Comment
  const handleAddComment = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedComplaint || !newCommentText.trim() || isSubmittingComment) return;

    setIsSubmittingComment(true);
    try {
      await createComplaintComment(selectedComplaint.id, newCommentText.trim());
      setNewCommentText("");
      const fresh = await getComplaint(selectedComplaint.id);
      setSelectedComplaint(fresh);
      chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
    } catch (err) {
      console.error("Failed to post comment:", err);
      alert(err instanceof ApiError ? err.message : "Failed to post comment");
    } finally {
      setIsSubmittingComment(false);
    }
  };

  // Submit New Complaint Form
  const handleCreateComplaintSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormSubmitError("");

    if (!formResident) {
      setFormSubmitError(t("modal.errResidentRequired"));
      return;
    }
    if (!formDescription.trim()) {
      setFormSubmitError(t("modal.errDescriptionRequired"));
      return;
    }

    setIsSubmittingForm(true);

    try {
      const formData = new FormData();
      formData.append("resident", formResident);
      formData.append("category", formCategory);
      formData.append("priority", formPriority);
      formData.append("description", formDescription.trim());
      if (formFile) {
        formData.append("attachment", formFile);
      }

      await createComplaint(formData);
      setIsLoggingNew(false);
      setFormDescription("");
      setFormFile(null);
      refreshData();
    } catch (err) {
      console.error("Failed to create complaint:", err);
      setFormSubmitError(err instanceof ApiError ? err.message : "Failed to submit complaint ticket.");
    } finally {
      setIsSubmittingForm(false);
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

  if (error) {
    return (
      <div className="space-y-4 max-w-md mx-auto py-16 text-center">
        <div className="flex size-14 items-center justify-center rounded-full bg-status-critical-soft text-status-critical border border-status-critical/10 mx-auto">
          <AlertTriangle className="size-6" />
        </div>
        <h3 className="text-lg font-bold text-ink">{t("errLoadFailed")}</h3>
        <p className="text-xs text-ink-muted leading-relaxed">{error}</p>
        <button
          onClick={refreshData}
          className="px-4 py-2 bg-surface-inverse text-ink-inverse text-xs font-semibold rounded-xl hover:opacity-90 transition-opacity cursor-pointer shadow-sm"
        >
          {t("retry")}
        </button>
      </div>
    );
  }

  // Count stats
  const totalCount = complaints.length;
  const openCount = complaints.filter((c) => c.status === "open").length;
  const inProgressCount = complaints.filter((c) => c.status === "in_progress" || c.status === "assigned").length;
  const resolvedCount = complaints.filter((c) => c.status === "resolved" || c.status === "closed").length;

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-ink md:text-3xl font-display-lg">
            {t("title")}
          </h1>
          <p className="mt-1 text-sm text-ink-muted">
            {t("subtitle")}
          </p>
        </div>
        <button
          onClick={() => setIsLoggingNew(true)}
          className="inline-flex items-center justify-center gap-2 rounded-xl bg-accent px-4 py-2.5 text-sm font-semibold text-ink-inverse hover:bg-accent-hover hover:shadow-lg hover:shadow-blue-500/10 active:scale-[0.98] transition-all cursor-pointer self-start sm:self-auto"
        >
          <Plus className="size-4.5" />
          {t("logComplaint")}
        </button>
      </div>

      {/* KPI Stats Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-surface-card border border-border rounded-2xl p-4 shadow-sm space-y-1">
          <span className="text-xs text-ink-muted font-semibold">{t("stats.totalTickets")}</span>
          <p className="text-2xl font-extrabold text-ink font-mono">{totalCount}</p>
        </div>
        <div className="bg-surface-card border border-border rounded-2xl p-4 shadow-sm space-y-1">
          <span className="text-xs text-blue-600 font-semibold">{t("stats.openIssues")}</span>
          <p className="text-2xl font-extrabold text-blue-600 font-mono">{openCount}</p>
        </div>
        <div className="bg-surface-card border border-border rounded-2xl p-4 shadow-sm space-y-1">
          <span className="text-xs text-amber-600 font-semibold">{t("stats.inProgress")}</span>
          <p className="text-2xl font-extrabold text-amber-600 font-mono">{inProgressCount}</p>
        </div>
        <div className="bg-surface-card border border-border rounded-2xl p-4 shadow-sm space-y-1">
          <span className="text-xs text-emerald-600 font-semibold">{t("stats.resolvedClosed")}</span>
          <p className="text-2xl font-extrabold text-emerald-600 font-mono">{resolvedCount}</p>
        </div>
      </div>

      {/* Filters Bar */}
      <div className="bg-surface-card border border-border rounded-2xl p-4 shadow-sm grid grid-cols-1 sm:grid-cols-12 gap-3 items-center">
        {/* Search */}
        <div className="relative sm:col-span-6 lg:col-span-5">
          <span className="absolute inset-y-0 left-0 flex items-center pl-3.5 text-ink-faint">
            <Search className="size-4.5" />
          </span>
          <input
            type="text"
            placeholder={t("filters.searchPlaceholder")}
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full rounded-xl border border-border bg-surface-card py-2 pl-10 pr-4 text-xs text-ink outline-none transition-all focus:ring-2 focus:ring-accent"
          />
        </div>

        {/* Status Select */}
        <div className="sm:col-span-2 lg:col-span-2">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-xs text-ink outline-none focus:ring-2 focus:ring-accent"
          >
            <option value="all">{t("filters.allStatuses")}</option>
            <option value="open">{t("statuses.open")}</option>
            <option value="assigned">{t("statuses.assigned")}</option>
            <option value="in_progress">{t("statuses.in_progress")}</option>
            <option value="resolved">{t("statuses.resolved")}</option>
            <option value="closed">{t("statuses.closed")}</option>
          </select>
        </div>

        {/* Category Select */}
        <div className="sm:col-span-2 lg:col-span-2">
          <select
            value={categoryFilter}
            onChange={(e) => setCategoryFilter(e.target.value)}
            className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-xs text-ink outline-none focus:ring-2 focus:ring-accent"
          >
            <option value="all">{t("filters.allCategories")}</option>
            <option value="electrical">{t("categories.electrical")}</option>
            <option value="plumbing">{t("categories.plumbing")}</option>
            <option value="internet_wifi">{t("categories.internet_wifi")}</option>
            <option value="housekeeping">{t("categories.housekeeping")}</option>
            <option value="security">{t("categories.security")}</option>
            <option value="furniture">{t("categories.furniture")}</option>
            <option value="other">{t("categories.other")}</option>
          </select>
        </div>

        {/* Priority Select */}
        <div className="sm:col-span-2 lg:col-span-3">
          <select
            value={priorityFilter}
            onChange={(e) => setPriorityFilter(e.target.value)}
            className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-xs text-ink outline-none focus:ring-2 focus:ring-accent"
          >
            <option value="all">{t("filters.allPriorities")}</option>
            <option value="low">{t("priorities.low")}</option>
            <option value="medium">{t("priorities.medium")}</option>
            <option value="high">{t("priorities.high")}</option>
            <option value="urgent">{t("priorities.urgent")}</option>
          </select>
        </div>
      </div>

      {/* Complaints List Table / Grid */}
      <div className="bg-surface-card border border-border rounded-2xl shadow-sm overflow-hidden">
        {filteredComplaints.length > 0 ? (
          <div className="divide-y divide-border text-xs">
            {filteredComplaints.map((c) => {
              const resName = c.resident_details
                ? `${c.resident_details.first_name} ${c.resident_details.last_name}`
                : c.resident_name || t("list.resident");
              const roomName = c.resident_details?.unit || c.resident_room || "--";
              const catObj = CATEGORY_MAP[c.category] || CATEGORY_MAP.other;
              const prioObj = PRIORITY_MAP[c.priority] || PRIORITY_MAP.medium;
              const CatIcon = catObj.icon;

              return (
                <div
                  key={c.id}
                  onClick={() => handleOpenDetail(c)}
                  className="p-5 hover:bg-surface-page/40 transition-colors cursor-pointer flex flex-col md:flex-row md:items-center justify-between gap-4"
                >
                  <div className="flex items-start gap-4">
                    <div className={`p-3 rounded-2xl border shrink-0 ${catObj.color}`}>
                      <CatIcon className="size-5" />
                    </div>
                    <div className="space-y-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-mono font-bold text-accent">#{c.id.substring(0, 8)}</span>
                        <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border ${prioObj.color}`}>
                          {t(`priorities.${c.priority as "low" | "medium" | "high" | "urgent"}`)}
                        </span>
                        <StatusPill
                          label={tStatus(c.status as "open" | "assigned" | "in_progress" | "resolved" | "closed") ?? c.status}
                          tone={getStatusTone(c.status)}
                        />
                      </div>
                      <h3 className="font-bold text-ink text-sm leading-snug line-clamp-1">{c.description}</h3>
                      <p className="text-ink-muted text-[11px] flex items-center gap-2 flex-wrap">
                        <span className="font-semibold text-ink">{resName}</span>
                        <span>·</span>
                        <span>{t("list.room")}: {roomName}</span>
                        <span>·</span>
                        <span>{c.created_at?.split("T")[0]}</span>
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center justify-between md:justify-end gap-4 shrink-0 border-t md:border-t-0 pt-3 md:pt-0 border-border">
                    <div className="text-right text-[11px]">
                      <span className="text-ink-faint block">{t("list.assignedTo")}</span>
                      <span className="font-semibold text-ink">
                        {c.assigned_to_details
                          ? `${c.assigned_to_details.first_name} ${c.assigned_to_details.last_name}`
                          : t("list.unassigned")}
                      </span>
                    </div>
                    <button className="text-accent hover:underline font-bold text-xs cursor-pointer">
                      {t("list.viewDetail")} ›
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center p-12 text-center space-y-3">
            <div className="flex size-12 items-center justify-center rounded-full bg-surface-page text-ink-muted border border-border">
              <Wrench className="size-6 text-ink-faint" />
            </div>
            <div className="space-y-1 max-w-sm">
              <h3 className="text-sm font-bold text-ink">{t("list.emptyTitle")}</h3>
              <p className="text-xs text-ink-muted leading-relaxed">
                {t("list.emptyDesc")}
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Ticket Detail Drawer / Modal */}
      {selectedComplaint && (
        <div className="fixed inset-0 z-50 flex items-center justify-end bg-on-surface/40 backdrop-blur-sm animate-fade-in">
          <div className="bg-surface-card border-l border-border max-w-xl w-full h-full p-6 shadow-2xl space-y-6 overflow-y-auto flex flex-col justify-between">
            <div className="space-y-6">
              {/* Header */}
              <div className="flex justify-between items-start border-b border-border pb-4">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs font-bold text-accent">
                      #{selectedComplaint.id.substring(0, 8)}
                    </span>
                    <StatusPill
                      label={tStatus(selectedComplaint.status as "open" | "assigned" | "in_progress" | "resolved" | "closed") ?? selectedComplaint.status}
                      tone={getStatusTone(selectedComplaint.status)}
                    />
                  </div>
                  <h2 className="text-lg font-bold text-ink mt-1 leading-snug">{selectedComplaint.description}</h2>
                </div>
                <button
                  onClick={() => setSelectedComplaint(null)}
                  className="p-1 rounded-lg text-ink-muted hover:bg-surface-page transition-colors cursor-pointer"
                >
                  <X className="size-5" />
                </button>
              </div>

              {/* Info Grid */}
              <div className="grid grid-cols-2 gap-4 text-xs bg-surface-page/50 border border-border rounded-xl p-4">
                <div>
                  <span className="text-ink-muted">{t("detail.raisedBy")}</span>
                  <p className="font-semibold text-ink mt-0.5">
                    {selectedComplaint.resident_details
                      ? `${selectedComplaint.resident_details.first_name} ${selectedComplaint.resident_details.last_name}`
                      : selectedComplaint.resident_name || "--"}
                  </p>
                </div>
                <div>
                  <span className="text-ink-muted">{t("detail.roomBed")}</span>
                  <p className="font-semibold text-ink mt-0.5">
                    {selectedComplaint.resident_details?.unit || selectedComplaint.resident_room || "--"}
                  </p>
                </div>
                <div>
                  <span className="text-ink-muted">{t("detail.loggedOn")}</span>
                  <p className="font-mono font-semibold text-ink mt-0.5">{selectedComplaint.created_at?.split("T")[0]}</p>
                </div>
                <div>
                  <span className="text-ink-muted">{t("modal.category")}</span>
                  <p className="font-semibold text-ink mt-0.5 capitalize">{t(`categories.${selectedComplaint.category as "electrical" | "plumbing" | "internet_wifi" | "housekeeping" | "security" | "furniture" | "other"}`)}</p>
                </div>
              </div>

              {/* Admin Actions: Assign & Status */}
              <div className="grid grid-cols-2 gap-4 text-xs">
                <div className="space-y-1">
                  <label className="font-semibold text-ink-muted">{t("detail.assignStaff")}</label>
                  <select
                    value={selectedComplaint.assigned_to || ""}
                    onChange={(e) => handleAssignStaff(e.target.value)}
                    className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-ink outline-none focus:ring-2 focus:ring-accent"
                  >
                    <option value="">{t("detail.selectStaff")}</option>
                    {staff.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.first_name} {s.last_name} ({s.role})
                      </option>
                    ))}
                  </select>
                </div>

                <div className="space-y-1">
                  <label className="font-semibold text-ink-muted">{t("detail.updateStatus")}</label>
                  <select
                    value={selectedComplaint.status}
                    onChange={(e) => handleStatusChange(e.target.value)}
                    className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-ink outline-none focus:ring-2 focus:ring-accent font-semibold"
                  >
                    <option value="open">{t("statuses.open")}</option>
                    <option value="assigned">{t("statuses.assigned")}</option>
                    <option value="in_progress">{t("statuses.in_progress")}</option>
                    <option value="resolved">{t("statuses.resolved")}</option>
                    <option value="closed">{t("statuses.closed")}</option>
                  </select>
                </div>
              </div>

              {/* Activity Log / Comments Timeline */}
              <div className="space-y-3 pt-2">
                <h3 className="text-xs font-bold uppercase tracking-wider text-ink-faint">
                  {t("detail.activityLog")}
                </h3>

                <div className="space-y-3 max-h-60 overflow-y-auto pr-1">
                  {selectedComplaint.comments && selectedComplaint.comments.length > 0 ? (
                    selectedComplaint.comments.map((cmt) => (
                      <div key={cmt.id} className="p-3 rounded-xl bg-surface-page border border-border text-xs space-y-1">
                        <div className="flex justify-between items-center text-[10px] text-ink-muted">
                          <span className="font-bold text-ink">
                            {cmt.author_details
                              ? `${cmt.author_details.first_name} ${cmt.author_details.last_name}`
                              : t("detail.staffFallback")}
                          </span>
                          <span className="font-mono">{cmt.created_at?.split("T")[0]}</span>
                        </div>
                        <p className="text-ink leading-relaxed">{cmt.body}</p>
                      </div>
                    ))
                  ) : (
                    <div className="p-4 text-center text-xs text-ink-muted italic border border-dashed border-border rounded-xl">
                      {t("detail.noComments")}
                    </div>
                  )}
                  <div ref={chatEndRef} />
                </div>
              </div>
            </div>

            {/* Comment Post Box */}
            <form onSubmit={handleAddComment} className="pt-4 border-t border-border flex items-center gap-2">
              <input
                type="text"
                placeholder={t("detail.addCommentPlaceholder")}
                value={newCommentText}
                onChange={(e) => setNewCommentText(e.target.value)}
                className="flex-1 rounded-xl border border-border bg-surface-card px-3.5 py-2 text-xs text-ink outline-none focus:ring-2 focus:ring-accent"
              />
              <button
                type="submit"
                disabled={isSubmittingComment || !newCommentText.trim()}
                className="p-2.5 rounded-xl bg-accent text-ink-inverse hover:bg-accent-hover transition-colors cursor-pointer disabled:opacity-50"
              >
                <Send className="size-4" />
              </button>
            </form>
          </div>
        </div>
      )}

      {/* Log New Complaint Modal */}
      {isLoggingNew && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-on-surface/40 backdrop-blur-sm animate-fade-in">
          <div className="bg-surface-card border border-border rounded-2xl max-w-lg w-full p-6 shadow-2xl space-y-4">
            <div className="flex justify-between items-center border-b border-border pb-3">
              <div>
                <h3 className="text-base font-bold text-ink">{t("modal.title")}</h3>
                <p className="text-xs text-ink-muted mt-0.5">{t("modal.subtitle")}</p>
              </div>
              <button
                onClick={() => setIsLoggingNew(false)}
                className="p-1 rounded-lg text-ink-muted hover:bg-surface-page transition-colors cursor-pointer"
              >
                <X className="size-5" />
              </button>
            </div>

            {formSubmitError && (
              <div className="p-3 rounded-xl bg-status-critical-soft border border-status-critical/20 text-status-critical text-xs font-semibold">
                {formSubmitError}
              </div>
            )}

            <form onSubmit={handleCreateComplaintSubmit} className="space-y-4 text-xs">
              <div className="space-y-1">
                <label className="font-semibold text-ink-muted">{t("modal.selectResident")}</label>
                <select
                  value={formResident}
                  onChange={(e) => setFormResident(e.target.value)}
                  className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2.5 text-ink outline-none focus:ring-2 focus:ring-accent"
                >
                  {residents.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.first_name} {r.last_name} ({r.unit || t("list.unassigned")})
                    </option>
                  ))}
                </select>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="font-semibold text-ink-muted">{t("modal.category")}</label>
                  <select
                    value={formCategory}
                    onChange={(e) => setFormCategory(e.target.value)}
                    className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2 text-ink outline-none focus:ring-2 focus:ring-accent"
                  >
                    <option value="electrical">{t("categories.electrical")}</option>
                    <option value="plumbing">{t("categories.plumbing")}</option>
                    <option value="internet_wifi">{t("categories.internet_wifi")}</option>
                    <option value="housekeeping">{t("categories.housekeeping")}</option>
                    <option value="security">{t("categories.security")}</option>
                    <option value="furniture">{t("categories.furniture")}</option>
                    <option value="other">{t("categories.other")}</option>
                  </select>
                </div>

                <div className="space-y-1">
                  <label className="font-semibold text-ink-muted">{t("modal.priority")}</label>
                  <select
                    value={formPriority}
                    onChange={(e) => setFormPriority(e.target.value)}
                    className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2 text-ink outline-none focus:ring-2 focus:ring-accent"
                  >
                    <option value="low">{t("priorities.low")}</option>
                    <option value="medium">{t("priorities.medium")}</option>
                    <option value="high">{t("priorities.high")}</option>
                    <option value="urgent">{t("priorities.urgent")}</option>
                  </select>
                </div>
              </div>

              <div className="space-y-1">
                <label className="font-semibold text-ink-muted">{t("modal.description")}</label>
                <textarea
                  rows={3}
                  placeholder={t("modal.descriptionPlaceholder")}
                  value={formDescription}
                  onChange={(e) => setFormDescription(e.target.value)}
                  className="w-full rounded-xl border border-border bg-surface-card p-3 text-ink outline-none focus:ring-2 focus:ring-accent resize-none"
                />
              </div>

              <div className="space-y-1">
                <label className="font-semibold text-ink-muted">{t("modal.attachFile")}</label>
                <input
                  ref={fileInputRef}
                  type="file"
                  onChange={(e) => setFormFile(e.target.files?.[0] || null)}
                  className="w-full text-xs text-ink-muted file:mr-3 file:py-1.5 file:px-3 file:rounded-xl file:border-0 file:text-xs file:font-semibold file:bg-surface-page file:text-ink hover:file:bg-surface-card cursor-pointer"
                />
              </div>

              <div className="flex justify-end gap-3 pt-3 border-t border-border">
                <button
                  type="button"
                  onClick={() => setIsLoggingNew(false)}
                  className="px-4 py-2 rounded-xl border border-border bg-surface-page font-bold text-ink-muted hover:bg-surface-card cursor-pointer"
                >
                  {t("modal.cancel")}
                </button>
                <button
                  type="submit"
                  disabled={isSubmittingForm}
                  className="px-4 py-2 rounded-xl bg-accent text-ink-inverse font-bold hover:bg-accent-hover transition-colors cursor-pointer disabled:opacity-50 inline-flex items-center gap-1.5"
                >
                  {isSubmittingForm ? (
                    <>
                      <LoaderCircle className="size-4 animate-spin" />
                      <span>{t("modal.submitting")}</span>
                    </>
                  ) : (
                    <span>{t("modal.submit")}</span>
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
