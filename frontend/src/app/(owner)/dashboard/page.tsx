"use client";

import React, { useState, useEffect, useMemo } from "react";
import { LoaderCircle, AlertTriangle } from "lucide-react";
import { ActiveIssuesCard } from "@/features/dashboard/ActiveIssuesCard";
import { DashboardHeader } from "@/features/dashboard/DashboardHeader";
import { DesktopHeader } from "@/features/dashboard/DesktopHeader";
import { FinancialsCard } from "@/features/dashboard/FinancialsCard";
import { OccupancyCard } from "@/features/dashboard/OccupancyCard";
import { QuickActions } from "@/features/dashboard/QuickActions";
import { TodaysActivity } from "@/features/dashboard/TodaysActivity";
import {
  listAllBeds,
  listComplaints,
  listInvoices,
  listPayments,
  listAdmissions,
  listResidents,
  type Bed,
  type Complaint,
  type Invoice,
  type Payment,
  type Admission,
  type Resident,
  ApiError
} from "@/lib/api";
import type { DashboardSummary, ActivityItem } from "@/features/dashboard/types";

export default function DashboardPage() {
  const [beds, setBeds] = useState<Bed[]>([]);
  const [complaints, setComplaints] = useState<Complaint[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [payments, setPayments] = useState<Payment[]>([]);
  const [admissions, setAdmissions] = useState<Admission[]>([]);
  const [residents, setResidents] = useState<Resident[]>([]);
  
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setTimeout(() => {
      setIsLoading(true);
      setError("");
    }, 0);

    Promise.all([
      listAllBeds(),
      listComplaints(),
      listInvoices(),
      listPayments(),
      listAdmissions(),
      listResidents()
    ])
      .then(([bedsData, complaintsData, invoicesData, paymentsData, admissionsData, residentsData]) => {
        if (cancelled) return;
        setBeds(bedsData);
        setComplaints(complaintsData);
        setInvoices(invoicesData);
        setPayments(paymentsData);
        setAdmissions(admissionsData);
        setResidents(residentsData);
        setIsLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        console.error(err);
        setError(err instanceof ApiError ? err.message : "Failed to load dashboard report metrics.");
        setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const summaryData = useMemo<DashboardSummary | null>(() => {
    if (isLoading || error) return null;

    // 1. Occupancy aggregation
    const totalBeds = beds.length;
    const occupiedBeds = beds.filter((b) => b.status === "occupied").length;
    const vacantBeds = totalBeds - occupiedBeds;
    const occupiedPercent = totalBeds > 0 ? parseFloat(((occupiedBeds / totalBeds) * 100).toFixed(1)) : 0;
    const vacantPercent = totalBeds > 0 ? parseFloat(((vacantBeds / totalBeds) * 100).toFixed(1)) : 0;

    // 2. Financials aggregation
    const now = new Date();
    // Sum monthly revenue for current month
    const thisMonthPayments = payments.filter((p) => {
      const d = new Date(p.payment_date);
      return d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear();
    });
    const monthlyRev = thisMonthPayments.reduce((acc, p) => acc + parseFloat(p.amount), 0);
    
    // Revenue delta calculation compared to last month
    const lastMonth = now.getMonth() === 0 ? 11 : now.getMonth() - 1;
    const lastMonthYear = now.getMonth() === 0 ? now.getFullYear() - 1 : now.getFullYear();
    const lastMonthPayments = payments.filter((p) => {
      const d = new Date(p.payment_date);
      return d.getMonth() === lastMonth && d.getFullYear() === lastMonthYear;
    });
    const lastMonthRev = lastMonthPayments.reduce((acc, p) => acc + parseFloat(p.amount), 0);
    const diff = monthlyRev - lastMonthRev;
    const direction = diff >= 0 ? "up" as const : "down" as const;
    const deltaPct = lastMonthRev > 0 ? ((Math.abs(diff) / lastMonthRev) * 100).toFixed(1) : "0";
    const deltaLabel = diff >= 0 ? `+${deltaPct}% vs last month` : `-${deltaPct}% vs last month`;

    // Outstanding dues (invoices issued or partially paid)
    const unpaidInvoices = invoices.filter((i) => i.status === "issued" || i.status === "partially_paid");
    const totalOutstanding = unpaidInvoices.reduce((acc, i) => acc + parseFloat(i.balance_due), 0);

    // Security deposits held
    const totalDeposits = admissions.reduce((acc, a) => acc + parseFloat(a.advance_amount), 0);

    // 3. Active issues (unresolved complaints)
    const activeComplaints = complaints.filter(
      (c) => c.status === "open" || c.status === "assigned" || c.status === "in_progress"
    );
    const mappedIssues = activeComplaints.slice(0, 3).map((c) => ({
      id: c.id,
      unit: c.resident_details?.unit || "N/A",
      issue: c.description,
      status: c.status === "assigned" ? ("open" as const) : (c.status as "open" | "in_progress" | "resolved")
    }));
    const highPriorityCount = activeComplaints.filter((c) => c.priority === "high" || c.priority === "urgent").length;

    // 4. Activity feed construction
    const feed: Array<{ id: string; tone: "info" | "good" | "neutral"; text: string; date: Date; timestamp: string }> = [];
    
    // Admissions (Check-ins)
    admissions.forEach((a) => {
      const r = residents.find((res) => res.id === a.resident);
      const name = r ? `${r.first_name} ${r.last_name || ""}`.trim() : "Resident";
      const room = r?.unit || "N/A";
      const d = new Date(a.joining_date);
      feed.push({
        id: `adm-${a.id}`,
        tone: "info",
        text: `New resident **${name}** checked into ${room}.`,
        date: d,
        timestamp: d.toLocaleDateString("en-IN", { month: "short", day: "numeric" })
      });
    });

    // Payments received
    payments.forEach((p) => {
      const inv = invoices.find((i) => i.id === p.invoice);
      const r = inv ? residents.find((res) => res.id === inv.resident) : null;
      const room = r?.unit || "Room";
      const d = new Date(p.payment_date);
      feed.push({
        id: `pay-${p.id}`,
        tone: "good",
        text: `Rent payment received for ${room} (₹${parseFloat(p.amount).toLocaleString("en-IN")}).`,
        date: d,
        timestamp: d.toLocaleDateString("en-IN", { month: "short", day: "numeric" })
      });
    });

    // Complaints logged
    complaints.forEach((c) => {
      const room = c.resident_details?.unit || "Room";
      const d = new Date(c.created_at);
      feed.push({
        id: `comp-${c.id}`,
        tone: "neutral",
        text: `New complaint logged for ${room} (${c.category.replace("_", " ")}).`,
        date: d,
        timestamp: d.toLocaleDateString("en-IN", { month: "short", day: "numeric" })
      });
    });

    // Sort descending by date
    const sortedFeed: ActivityItem[] = feed
      .sort((a, b) => b.date.getTime() - a.date.getTime())
      .slice(0, 5)
      .map((item) => ({
        id: item.id,
        tone: item.tone,
        text: item.text,
        timestamp: item.timestamp
      }));

    return {
      occupancy: {
        totalBeds,
        occupiedBeds,
        vacantBeds,
        occupiedPercent,
        vacantPercent
      },
      financials: {
        monthlyRevenue: `₹${monthlyRev.toLocaleString("en-IN")}`,
        revenueDelta: { direction, label: deltaLabel },
        outstandingDues: `₹${totalOutstanding.toLocaleString("en-IN")}`,
        securityDeposits: `₹${totalDeposits.toLocaleString("en-IN")}`
      },
      issues: mappedIssues,
      highPriorityIssueCount: highPriorityCount,
      activity: sortedFeed
    };
  }, [isLoading, error, beds, complaints, invoices, payments, admissions, residents]);

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-32 text-sm text-ink-muted">
        <LoaderCircle className="size-8 animate-spin text-accent" />
        <p className="font-semibold mt-2">Loading dashboard report summary...</p>
      </div>
    );
  }

  if (error || !summaryData) {
    return (
      <div className="space-y-4 max-w-md mx-auto py-16 text-center">
        <div className="flex size-14 items-center justify-center rounded-full bg-status-critical-soft text-status-critical border border-status-critical/10 mx-auto">
          <AlertTriangle className="size-6" />
        </div>
        <h3 className="text-lg font-bold text-ink">Failed to Load Dashboard</h3>
        <p className="text-sm text-ink-muted leading-relaxed">
          {error || "Could not retrieve tenant reporting summary metrics."}
        </p>
      </div>
    );
  }

  return (
    <>
      {/* Mobile */}
      <div className="mx-auto flex max-w-md flex-col gap-4 pb-6 md:hidden">
        <DashboardHeader />
        <QuickActions />
        <div className="flex flex-col gap-4 px-4">
          <OccupancyCard data={summaryData.occupancy} />
          <FinancialsCard data={summaryData.financials} />
          <ActiveIssuesCard
            issues={summaryData.issues}
            highPriorityCount={summaryData.highPriorityIssueCount}
          />
        </div>
      </div>

      {/* Desktop */}
      <div className="hidden md:block">
        <DesktopHeader />
        <div className="flex flex-col gap-6 p-8">
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-[2fr_1fr]">
            <OccupancyCard data={summaryData.occupancy} />
            <FinancialsCard data={summaryData.financials} />
          </div>
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-[2fr_1fr]">
            <ActiveIssuesCard
              issues={summaryData.issues}
              highPriorityCount={summaryData.highPriorityIssueCount}
            />
            <TodaysActivity items={summaryData.activity} />
          </div>
        </div>
      </div>
    </>
  );
}
