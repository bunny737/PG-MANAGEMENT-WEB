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
  CheckCircle,
  Play,
  ShieldAlert,
  Clock,
  Lock,
  Paperclip,
  AlertCircle
} from "lucide-react";
import { getInitials } from "@/lib/utils";
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
  type CurrentUser,
  ApiError
} from "@/lib/api";

const CATEGORY_MAP: Record<string, { label: string; icon: React.ComponentType<{ className?: string }>; color: string }> = {
  electrical: { label: "Electrical", icon: Wrench, color: "text-amber-500 bg-amber-50 border-amber-100" },
  plumbing: { label: "Plumbing", icon: Wrench, color: "text-blue-500 bg-blue-50 border-blue-100" },
  internet_wifi: { label: "Internet & WiFi", icon: Wrench, color: "text-indigo-500 bg-indigo-50 border-indigo-100" },
  housekeeping: { label: "Housekeeping", icon: Wrench, color: "text-teal-500 bg-teal-50 border-teal-100" },
  security: { label: "Security", icon: ShieldAlert, color: "text-rose-500 bg-rose-50 border-rose-100" },
  furniture: { label: "Furniture", icon: Wrench, color: "text-orange-500 bg-orange-50 border-orange-100" },
  other: { label: "Other", icon: AlertCircle, color: "text-slate-500 bg-slate-50 border-slate-100" }
};

const PRIORITY_MAP: Record<string, { label: string; color: string }> = {
  low: { label: "Low Priority", color: "bg-slate-50 border-slate-200 text-slate-500" },
  medium: { label: "Medium Priority", color: "bg-sky-50 border-sky-100 text-sky-600" },
  high: { label: "High Priority", color: "bg-orange-50 border-orange-200 text-orange-600" },
  urgent: { label: "Urgent Priority", color: "bg-rose-50 border-rose-200 text-rose-600 font-bold" }
};

const STATUS_MAP: Record<string, { label: string; color: string; order: number }> = {
  open: { label: "Open", color: "bg-blue-50 border-blue-100 text-blue-600", order: 1 },
  assigned: { label: "Assigned", color: "bg-indigo-50 border-indigo-100 text-indigo-600", order: 2 },
  in_progress: { label: "In Progress", color: "bg-amber-50 border-amber-100 text-amber-600", order: 3 },
  resolved: { label: "Resolved", color: "bg-emerald-50 border-emerald-100 text-emerald-600", order: 4 },
  closed: { label: "Closed", color: "bg-slate-100 border-slate-200 text-slate-500", order: 5 }
};

export function ComplaintsDashboard() {
  const [complaints, setComplaints] = useState<Complaint[]>([]);
  const [residents, setResidents] = useState<Resident[]>([]);
  const [staff, setStaff] = useState<StaffUser[]>([]);
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");

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

  const loadData = () => {
    setTimeout(() => setIsLoading(true), 0);
    setError("");

    Promise.all([
      listComplaints(),
      listResidents(),
      listStaff().catch(() => [] as StaffUser[]), // Fallback if staff listing fails
      getCurrentUser().catch(() => null)
    ])
      .then(([complaintsData, residentsData, staffData, userData]) => {
        setComplaints(complaintsData);
        setResidents(residentsData.filter(r => ["active", "reserved", "notice_period"].includes(r.status)));
        setStaff(staffData);
        setCurrentUser(userData);
        setIsLoading(false);
      })
      .catch((err) => {
        console.error(err);
        setError("Failed to fetch complaints list. Please check your network connection.");
        setIsLoading(false);
      });
  };

  useEffect(() => {
    const timer = setTimeout(() => {
      loadData();
    }, 0);
    return () => clearTimeout(timer);
  }, []);

  // Scroll to bottom of chat when comments change
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [selectedComplaint?.comments]);

  // Handle reload details for active drawer
  const refreshActiveComplaint = (id: string) => {
    getComplaint(id)
      .then((data) => {
        setSelectedComplaint(data);
        // Also refresh list
        listComplaints().then(setComplaints).catch(console.error);
      })
      .catch(console.error);
  };

  // Status transitions
  const handleAssign = (assignedToId: string) => {
    if (!selectedComplaint) return;
    assignComplaint(selectedComplaint.id, assignedToId)
      .then(() => refreshActiveComplaint(selectedComplaint.id))
      .catch((err) => alert(err instanceof ApiError ? err.message : "Assignment failed"));
  };

  const handleStatusChange = (nextStatus: string) => {
    if (!selectedComplaint) return;
    updateComplaintStatus(selectedComplaint.id, nextStatus)
      .then(() => refreshActiveComplaint(selectedComplaint.id))
      .catch((err) => alert(err instanceof ApiError ? err.message : "Status transition failed"));
  };

  // Submit comments
  const handleAddComment = (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedComplaint || !newCommentText.trim() || isSubmittingComment) return;

    setIsSubmittingComment(true);
    createComplaintComment(selectedComplaint.id, newCommentText.trim())
      .then(() => {
        setNewCommentText("");
        setIsSubmittingComment(false);
        refreshActiveComplaint(selectedComplaint.id);
      })
      .catch((err) => {
        console.error(err);
        setIsSubmittingComment(false);
      });
  };

  // Log new Complaint
  const handleLogComplaintSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!formResident || !formDescription.trim() || isSubmittingForm) {
      setFormSubmitError("Please fill out all required fields.");
      return;
    }

    setIsSubmittingForm(true);
    setFormSubmitError("");

    const fd = new FormData();
    fd.append("resident", formResident);
    fd.append("category", formCategory);
    fd.append("priority", formPriority);
    fd.append("description", formDescription.trim());
    if (formFile) {
      fd.append("attachment", formFile);
    }

    createComplaint(fd)
      .then(() => {
        // Reset form
        setFormResident("");
        setFormCategory("electrical");
        setFormPriority("medium");
        setFormDescription("");
        setFormFile(null);
        if (fileInputRef.current) fileInputRef.current.value = "";
        
        setIsLoggingNew(false);
        setIsSubmittingForm(false);
        loadData();
      })
      .catch((err) => {
        console.error(err);
        setFormSubmitError(err instanceof ApiError ? err.message : "Failed to log complaint. Please try again.");
        setIsSubmittingForm(false);
      });
  };

  // Counters
  const stats = useMemo(() => {
    const counts = { total: 0, open: 0, in_progress: 0, resolved: 0, closed: 0 };
    complaints.forEach((c) => {
      counts.total++;
      if (c.status === "open") counts.open++;
      else if (c.status === "assigned" || c.status === "in_progress") counts.in_progress++;
      else if (c.status === "resolved") counts.resolved++;
      else if (c.status === "closed") counts.closed++;
    });
    return counts;
  }, [complaints]);

  // Filtered List
  const filteredComplaints = useMemo(() => {
    return complaints.filter((c) => {
      // Status filter
      let matchStatus = true;
      if (statusFilter !== "all") {
        if (statusFilter === "in_progress") {
          matchStatus = c.status === "in_progress" || c.status === "assigned";
        } else {
          matchStatus = c.status === statusFilter;
        }
      }

      // Category filter
      const matchCategory = categoryFilter === "all" ? true : c.category === categoryFilter;

      // Priority filter
      const matchPriority = priorityFilter === "all" ? true : c.priority === priorityFilter;

      // Search term
      let matchSearch = true;
      if (searchTerm.trim()) {
        const query = searchTerm.toLowerCase();
        const residentName = `${c.resident_details?.first_name || ""} ${c.resident_details?.last_name || ""}`.toLowerCase();
        const unit = (c.resident_details?.unit || "").toLowerCase();
        const desc = c.description.toLowerCase();
        matchSearch = residentName.includes(query) || unit.includes(query) || desc.includes(query);
      }

      return matchStatus && matchCategory && matchPriority && matchSearch;
    });
  }, [complaints, statusFilter, categoryFilter, priorityFilter, searchTerm]);

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-32 text-sm text-ink-muted">
        <LoaderCircle className="size-8 animate-spin text-accent" />
        <p className="font-semibold mt-2">Loading complaints dashboard...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {error && (
        <div className="flex gap-2 rounded-xl bg-status-critical-soft p-3.5 text-xs text-status-critical border border-status-critical/10">
          <AlertTriangle className="size-4 shrink-0" />
          <p className="font-semibold">{error}</p>
        </div>
      )}
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-ink">Complaints & Tickets</h1>
          <p className="text-sm text-ink-muted">Drive resident issues and maintenance tickets through their lifecycle.</p>
        </div>
        <button
          onClick={() => setIsLoggingNew(true)}
          className="flex items-center justify-center gap-2 rounded-xl bg-accent px-4 py-2.5 text-sm font-bold text-white hover:bg-accent-hover transition-all cursor-pointer shadow-sm shadow-accent/15"
        >
          <Plus className="size-4" />
          Log Complaint
        </button>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <div className="rounded-2xl border border-border bg-surface-card p-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-ink-muted">Total Tickets</p>
          <p className="mt-2 text-2xl font-bold text-ink">{stats.total}</p>
        </div>
        <div className="rounded-2xl border border-border bg-surface-card p-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-ink-muted">Unassigned/Open</p>
          <p className="mt-2 text-2xl font-bold text-blue-600">{stats.open}</p>
        </div>
        <div className="rounded-2xl border border-border bg-surface-card p-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-ink-muted">In Progress</p>
          <p className="mt-2 text-2xl font-bold text-amber-600">{stats.in_progress}</p>
        </div>
        <div className="rounded-2xl border border-border bg-surface-card p-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-ink-muted">Resolved</p>
          <p className="mt-2 text-2xl font-bold text-emerald-600">{stats.resolved}</p>
        </div>
        <div className="rounded-2xl border border-border bg-surface-card p-4 col-span-2 lg:col-span-1">
          <p className="text-xs font-semibold uppercase tracking-wider text-ink-muted">Closed</p>
          <p className="mt-2 text-2xl font-bold text-slate-500">{stats.closed}</p>
        </div>
      </div>

      {/* Filters Panel */}
      <div className="rounded-2xl border border-border bg-surface-card p-4 space-y-4">
        {/* Status Tabs selectors */}
        <div className="flex gap-1.5 overflow-x-auto border-b border-border pb-1">
          {[
            { id: "all", label: "All Tickets" },
            { id: "open", label: "Open" },
            { id: "in_progress", label: "In Progress" },
            { id: "resolved", label: "Resolved" },
            { id: "closed", label: "Closed" }
          ].map((tab) => {
            const active = statusFilter === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setStatusFilter(tab.id)}
                className={`border-b-2 px-3.5 py-2 text-xs font-bold whitespace-nowrap transition-all cursor-pointer ${
                  active ? "border-accent text-accent" : "border-transparent text-ink-muted hover:text-ink"
                }`}
              >
                {tab.label}
              </button>
            );
          })}
        </div>

        {/* Inputs */}
        <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
          {/* Search */}
          <div className="relative md:col-span-2">
            <Search className="absolute inset-y-0 left-3.5 my-auto size-4 text-ink-muted" />
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Search by resident name, room, description..."
              className="w-full rounded-xl border border-border bg-surface-card py-2.5 pl-10 pr-4 text-sm text-ink outline-none transition-all focus:ring-4 focus:ring-accent/15 focus:border-accent"
            />
          </div>

          {/* Category Filter */}
          <select
            value={categoryFilter}
            onChange={(e) => setCategoryFilter(e.target.value)}
            className="rounded-xl border border-border bg-surface-card px-3.5 py-2.5 text-sm text-ink-muted outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent"
          >
            <option value="all">All Categories</option>
            <option value="electrical">Electrical</option>
            <option value="plumbing">Plumbing</option>
            <option value="internet_wifi">Internet & WiFi</option>
            <option value="housekeeping">Housekeeping</option>
            <option value="security">Security</option>
            <option value="furniture">Furniture</option>
            <option value="other">Other</option>
          </select>

          {/* Priority Filter */}
          <select
            value={priorityFilter}
            onChange={(e) => setPriorityFilter(e.target.value)}
            className="rounded-xl border border-border bg-surface-card px-3.5 py-2.5 text-sm text-ink-muted outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent"
          >
            <option value="all">All Priorities</option>
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
            <option value="urgent">Urgent</option>
          </select>
        </div>
      </div>

      {/* Grid List */}
      {filteredComplaints.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-border bg-surface-card py-16 text-center">
          <AlertTriangle className="size-10 text-ink-muted" />
          <h3 className="mt-4 text-base font-bold text-ink">No Tickets Found</h3>
          <p className="mt-1 text-sm text-ink-muted">No complaints match your query parameters.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {filteredComplaints.map((c) => {
            const cat = CATEGORY_MAP[c.category] || CATEGORY_MAP.other;
            const prio = PRIORITY_MAP[c.priority] || PRIORITY_MAP.medium;
            const stat = STATUS_MAP[c.status] || STATUS_MAP.open;
            const residentName = `${c.resident_details?.first_name || ""} ${c.resident_details?.last_name || ""}`;
            const initials = getInitials(residentName);
            const CatIcon = cat.icon;

            return (
              <div
                key={c.id}
                onClick={() => refreshActiveComplaint(c.id)}
                className="group relative flex flex-col justify-between rounded-2xl border border-border bg-surface-card p-5 hover:border-accent/40 hover:shadow-md transition-all cursor-pointer"
              >
                <div>
                  {/* Category, Priority and Status */}
                  <div className="flex items-center justify-between gap-2 border-b border-border/60 pb-3">
                    <div className="flex items-center gap-2">
                      <span className={`inline-flex size-7 items-center justify-center rounded-lg border ${cat.color}`}>
                        <CatIcon className="size-4" />
                      </span>
                      <span className="text-xs font-bold text-ink uppercase tracking-wider">{cat.label}</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <span className={`rounded-full px-2.5 py-0.5 text-[10px] font-bold border ${prio.color}`}>
                        {prio.label}
                      </span>
                      <span className={`rounded-full px-2.5 py-0.5 text-[10px] font-bold border ${stat.color}`}>
                        {stat.label}
                      </span>
                    </div>
                  </div>

                  {/* Body details */}
                  <div className="mt-4 space-y-2">
                    <p className="text-sm font-semibold text-ink line-clamp-2 leading-relaxed">
                      {c.description}
                    </p>

                    <div className="flex items-center gap-2 pt-2">
                      <div className="flex size-7 items-center justify-center rounded-full bg-accent/5 text-xs font-bold text-accent border border-accent/10">
                        {initials}
                      </div>
                      <div>
                        <p className="text-xs font-bold text-ink">{residentName}</p>
                        <p className="text-[10px] font-medium text-ink-muted">
                          {c.resident_details?.block} &bull; {c.resident_details?.unit}
                        </p>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Footer metadata */}
                <div className="mt-4 flex items-center justify-between gap-4 border-t border-border/40 pt-3 text-[11px] text-ink-muted">
                  <div className="flex items-center gap-1">
                    <Clock className="size-3" />
                    <span>Logged {new Date(c.created_at).toLocaleDateString()}</span>
                  </div>
                  <div className="font-semibold">
                    {c.assigned_to_details ? (
                      <span className="text-indigo-600">Assigned: {c.assigned_to_details.first_name}</span>
                    ) : (
                      <span className="text-amber-600 font-bold">Unassigned</span>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Details Slide-over Drawer */}
      {selectedComplaint && (
        <div className="fixed inset-0 z-50 flex justify-end bg-ink/40 backdrop-blur-sm transition-all duration-300">
          <div className="absolute inset-0" onClick={() => setSelectedComplaint(null)} />
          
          <div className="relative flex h-full w-full max-w-lg flex-col bg-surface-card shadow-2xl border-l border-border transition-all duration-300 animate-slide-in">
            {/* Header */}
            <div className="flex items-center justify-between border-b border-border p-4">
              <div>
                <h2 className="text-base font-bold text-ink">Ticket Details</h2>
                <p className="text-xs text-ink-muted">Ref #{selectedComplaint.id.slice(0, 8)}</p>
              </div>
              <button
                onClick={() => setSelectedComplaint(null)}
                className="rounded-lg p-1.5 text-ink-muted hover:bg-slate-50 transition-colors"
              >
                <X className="size-5" />
              </button>
            </div>

            {/* Content Body */}
            <div className="flex-1 overflow-y-auto p-5 space-y-6">
              {/* Header Badges */}
              <div className="flex flex-wrap gap-2">
                <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-bold border ${CATEGORY_MAP[selectedComplaint.category]?.color || CATEGORY_MAP.other.color}`}>
                  {CATEGORY_MAP[selectedComplaint.category]?.label}
                </span>
                <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-bold border ${PRIORITY_MAP[selectedComplaint.priority]?.color}`}>
                  {PRIORITY_MAP[selectedComplaint.priority]?.label}
                </span>
                <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-bold border ${STATUS_MAP[selectedComplaint.status]?.color}`}>
                  {STATUS_MAP[selectedComplaint.status]?.label}
                </span>
              </div>

              {/* Description */}
              <div className="space-y-1.5">
                <h4 className="text-xs font-semibold uppercase tracking-wider text-ink-muted">Description</h4>
                <div className="rounded-xl bg-slate-50 p-4 border border-slate-100 text-sm text-ink leading-relaxed">
                  {selectedComplaint.description}
                </div>
              </div>

              {/* Photo Attachment if present */}
              {selectedComplaint.attachment && (
                <div className="space-y-1.5">
                  <h4 className="text-xs font-semibold uppercase tracking-wider text-ink-muted">Attachment</h4>
                  <div className="overflow-hidden rounded-xl border border-border bg-slate-50 max-h-48 flex items-center justify-center">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={selectedComplaint.attachment}
                      alt="Complaint Attachment"
                      className="max-w-full max-h-full object-contain hover:scale-105 transition-transform"
                    />
                  </div>
                </div>
              )}

              {/* Resident Card details */}
              <div className="space-y-1.5">
                <h4 className="text-xs font-semibold uppercase tracking-wider text-ink-muted">Resident details</h4>
                <div className="flex items-center gap-3 rounded-xl border border-border p-3.5">
                  <div className="flex size-10 items-center justify-center rounded-full bg-accent/5 text-sm font-bold text-accent border border-accent/10">
                    {getInitials(`${selectedComplaint.resident_details?.first_name || ""} ${selectedComplaint.resident_details?.last_name || ""}`)}
                  </div>
                  <div>
                    <h5 className="text-sm font-bold text-ink">
                      {selectedComplaint.resident_details?.first_name} {selectedComplaint.resident_details?.last_name}
                    </h5>
                    <p className="text-xs text-ink-muted">
                      {selectedComplaint.resident_details?.block} &bull; {selectedComplaint.resident_details?.unit}
                    </p>
                  </div>
                </div>
              </div>

              {/* Workflow Status Progression & Actions */}
              <div className="space-y-3 rounded-2xl border border-border p-4 bg-slate-50/50">
                <h4 className="text-xs font-bold uppercase tracking-wider text-ink">Workflow Lifecycle</h4>
                
                {/* Visual workflow timeline */}
                <div className="flex items-center justify-between gap-1 py-2">
                  {["open", "assigned", "in_progress", "resolved", "closed"].map((step, idx) => {
                    const currentIdx = STATUS_MAP[selectedComplaint.status]?.order || 1;
                    const stepIdx = STATUS_MAP[step].order;
                    const isActive = step === selectedComplaint.status;
                    const isCompleted = stepIdx < currentIdx;

                    return (
                      <React.Fragment key={step}>
                        <div className="flex flex-col items-center gap-1.5 flex-1">
                          <div className={`flex size-6 items-center justify-center rounded-full border transition-all ${
                            isActive
                              ? "bg-accent border-accent text-white scale-110 shadow-sm"
                              : isCompleted
                              ? "bg-emerald-500 border-emerald-500 text-white"
                              : "bg-white border-border text-ink-muted"
                          }`}>
                            {isCompleted ? <CheckCircle className="size-3.5" /> : <span className="text-[10px] font-bold">{stepIdx}</span>}
                          </div>
                          <span className={`text-[9px] font-bold uppercase tracking-wider ${isActive ? "text-accent" : "text-ink-muted"}`}>
                            {STATUS_MAP[step].label}
                          </span>
                        </div>
                        {idx < 4 && <div className={`h-[2px] flex-1 ${stepIdx < currentIdx ? "bg-emerald-500" : "bg-border"}`} />}
                      </React.Fragment>
                    );
                  })}
                </div>

                {/* Transitions Action Panel */}
                <div className="border-t border-border pt-3">
                  {/* Status: Open -> Assign staff */}
                  {selectedComplaint.status === "open" && (
                    <div className="space-y-2">
                      <p className="text-xs font-medium text-ink-muted">Assign this ticket to start the workflow:</p>
                      <select
                        onChange={(e) => {
                          if (e.target.value) handleAssign(e.target.value);
                        }}
                        defaultValue=""
                        className="w-full rounded-xl border border-border bg-white px-3.5 py-2.5 text-xs text-ink-muted outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent"
                      >
                        <option value="" disabled>Select Staff Assignee...</option>
                        {staff.map((s) => (
                          <option key={s.id} value={s.id}>
                            {s.first_name} {s.last_name} ({s.role})
                          </option>
                        ))}
                      </select>
                    </div>
                  )}

                  {/* Status: Assigned -> Start work */}
                  {selectedComplaint.status === "assigned" && (
                    <button
                      onClick={() => handleStatusChange("in_progress")}
                      className="flex w-full items-center justify-center gap-2 rounded-xl bg-accent px-4 py-2.5 text-xs font-bold text-white hover:bg-accent-hover transition-colors shadow-sm cursor-pointer"
                    >
                      <Play className="size-3.5" />
                      Start Work (Mark In Progress)
                    </button>
                  )}

                  {/* Status: In Progress -> Mark resolved */}
                  {selectedComplaint.status === "in_progress" && (
                    <button
                      onClick={() => handleStatusChange("resolved")}
                      className="flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-600 px-4 py-2.5 text-xs font-bold text-white hover:bg-emerald-700 transition-colors shadow-sm cursor-pointer"
                    >
                      <CheckCircle className="size-3.5" />
                      Mark Resolved
                    </button>
                  )}

                  {/* Status: Resolved -> Close ticket */}
                  {selectedComplaint.status === "resolved" && (
                    <button
                      onClick={() => handleStatusChange("closed")}
                      className="flex w-full items-center justify-center gap-2 rounded-xl bg-slate-600 px-4 py-2.5 text-xs font-bold text-white hover:bg-slate-700 transition-colors shadow-sm cursor-pointer"
                    >
                      <Lock className="size-3.5" />
                      Close Ticket (Lock)
                    </button>
                  )}

                  {/* Status: Closed */}
                  {selectedComplaint.status === "closed" && (
                    <div className="flex items-center justify-center gap-2 rounded-xl bg-slate-100 p-2.5 text-center text-xs font-bold text-slate-500 border border-slate-200">
                      <Lock className="size-3.5" />
                      Ticket is closed and archived
                    </div>
                  )}
                </div>
              </div>

              {/* Comments Chat Thread */}
              <div className="space-y-3">
                <h4 className="text-xs font-semibold uppercase tracking-wider text-ink-muted">Activity Comments Thread</h4>
                <div className="flex flex-col gap-3 rounded-2xl border border-border bg-slate-50/20 p-4 max-h-72 overflow-y-auto">
                  {selectedComplaint.comments?.length === 0 ? (
                    <p className="text-center text-xs text-ink-muted py-6">No activity updates yet. Send a note below.</p>
                  ) : (
                    selectedComplaint.comments?.map((comment) => {
                      const isCurrentUser = comment.author_details?.id === currentUser?.id;
                      const authorName = `${comment.author_details?.first_name || "Staff"} ${comment.author_details?.last_name || ""}`.trim();
                      const roleLabel = comment.author_details?.role ? ` (${comment.author_details.role})` : "";

                      return (
                        <div
                          key={comment.id}
                          className={`flex flex-col max-w-[85%] rounded-2xl p-3 text-xs leading-relaxed shadow-sm ${
                            isCurrentUser
                              ? "bg-accent/10 border border-accent/15 self-end text-right text-ink"
                              : "bg-white border border-border self-start text-left text-ink"
                          }`}
                        >
                          <p className="text-[10px] font-bold text-ink-muted">
                            {authorName}
                            <span className="font-medium text-[9px]">{roleLabel}</span>
                          </p>
                          <p className="mt-1 font-medium text-ink break-words">{comment.body}</p>
                          <p className="mt-1.5 text-[9px] text-ink-muted/80">
                            {new Date(comment.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                          </p>
                        </div>
                      );
                    })
                  )}
                  <div ref={chatEndRef} />
                </div>

                {/* Add Comment input Form */}
                <form onSubmit={handleAddComment} className="flex gap-2">
                  <input
                    type="text"
                    value={newCommentText}
                    onChange={(e) => setNewCommentText(e.target.value)}
                    placeholder="Enter progress update comment..."
                    disabled={isSubmittingComment}
                    className="flex-1 rounded-xl border border-border bg-white px-3.5 py-2.5 text-xs text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent"
                  />
                  <button
                    type="submit"
                    disabled={isSubmittingComment || !newCommentText.trim()}
                    className="flex items-center justify-center rounded-xl bg-accent px-4 py-2.5 text-white hover:bg-accent-hover transition-colors disabled:opacity-50 cursor-pointer shadow-sm shadow-accent/10"
                  >
                    {isSubmittingComment ? (
                      <LoaderCircle className="size-4 animate-spin" />
                    ) : (
                      <Send className="size-4" />
                    )}
                  </button>
                </form>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Log Complaint Modal */}
      {isLoggingNew && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 backdrop-blur-sm p-4">
          <div className="w-full max-w-md rounded-2xl border border-border bg-surface-card p-6 shadow-2xl animate-fade-in space-y-4">
            <div className="flex items-center justify-between border-b border-border pb-3">
              <h2 className="text-base font-bold text-ink">Log Complaint Ticket</h2>
              <button
                onClick={() => setIsLoggingNew(false)}
                className="rounded-lg p-1.5 text-ink-muted hover:bg-slate-50 transition-colors"
              >
                <X className="size-5" />
              </button>
            </div>

            {formSubmitError && (
              <div className="flex gap-2 rounded-xl bg-status-critical-soft p-3 text-xs text-status-critical border border-status-critical/10">
                <AlertTriangle className="size-4 shrink-0" />
                <p className="font-semibold">{formSubmitError}</p>
              </div>
            )}

            <form onSubmit={handleLogComplaintSubmit} className="space-y-4">
              {/* Resident Dropdown */}
              <div className="space-y-1.5">
                <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                  Select Occupant/Resident *
                </label>
                <select
                  value={formResident}
                  onChange={(e) => setFormResident(e.target.value)}
                  required
                  className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2.5 text-sm text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent"
                >
                  <option value="">-- Choose Resident --</option>
                  {residents.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.first_name} {r.last_name} ({r.unit || "No Room"})
                    </option>
                  ))}
                </select>
              </div>

              <div className="grid grid-cols-2 gap-4">
                {/* Category */}
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                    Category *
                  </label>
                  <select
                    value={formCategory}
                    onChange={(e) => setFormCategory(e.target.value)}
                    required
                    className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2.5 text-sm text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent"
                  >
                    <option value="electrical">Electrical</option>
                    <option value="plumbing">Plumbing</option>
                    <option value="internet_wifi">Internet & WiFi</option>
                    <option value="housekeeping">Housekeeping</option>
                    <option value="security">Security</option>
                    <option value="furniture">Furniture</option>
                    <option value="other">Other</option>
                  </select>
                </div>

                {/* Priority */}
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                    Priority *
                  </label>
                  <select
                    value={formPriority}
                    onChange={(e) => setFormPriority(e.target.value)}
                    required
                    className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2.5 text-sm text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent"
                  >
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                    <option value="urgent">Urgent</option>
                  </select>
                </div>
              </div>

              {/* Description */}
              <div className="space-y-1.5">
                <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                  Issue Description *
                </label>
                <textarea
                  value={formDescription}
                  onChange={(e) => setFormDescription(e.target.value)}
                  required
                  rows={4}
                  placeholder="Provide precise details of the complaint (e.g. water leakage in bathroom, speed of WiFi, etc.)"
                  className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2.5 text-sm text-ink outline-none focus:ring-4 focus:ring-accent/15 focus:border-accent resize-none"
                />
              </div>

              {/* Photo Upload */}
              <div className="space-y-1.5">
                <label className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                  Photo Attachment (Optional)
                </label>
                <div className="flex items-center gap-3">
                  <input
                    type="file"
                    ref={fileInputRef}
                    accept="image/*"
                    onChange={(e) => setFormFile(e.target.files?.[0] || null)}
                    className="hidden"
                  />
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    className="flex items-center gap-2 rounded-xl border border-border bg-slate-50 px-4 py-2.5 text-xs font-bold text-ink-muted hover:text-ink transition-colors cursor-pointer"
                  >
                    <Paperclip className="size-4" />
                    {formFile ? formFile.name.slice(0, 20) : "Upload image..."}
                  </button>
                  {formFile && (
                    <button
                      type="button"
                      onClick={() => {
                        setFormFile(null);
                        if (fileInputRef.current) fileInputRef.current.value = "";
                      }}
                      className="rounded-lg p-1 text-rose-500 hover:bg-rose-50 transition-colors"
                    >
                      <X className="size-4" />
                    </button>
                  )}
                </div>
              </div>

              {/* Actions */}
              <div className="flex gap-3 pt-3 border-t border-border">
                <button
                  type="button"
                  onClick={() => setIsLoggingNew(false)}
                  className="flex-1 rounded-xl border border-border py-2.5 text-sm font-bold text-ink-muted hover:bg-slate-50 transition-colors cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmittingForm}
                  className="flex-1 flex items-center justify-center gap-2 rounded-xl bg-accent py-2.5 text-sm font-bold text-white hover:bg-accent-hover disabled:opacity-50 transition-colors cursor-pointer shadow-sm shadow-accent/15"
                >
                  {isSubmittingForm ? (
                    <LoaderCircle className="size-4 animate-spin" />
                  ) : (
                    "Save Ticket"
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
