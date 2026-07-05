"use client";

import React, { useState } from "react";
import Link from "next/link";
import { ChevronRight, Wrench, CheckCircle, User, Calendar, CheckCircle2 } from "lucide-react";
import { mockProperties, Bed } from "./mock-properties";

export function BedDetails({
  propertyId,
  floorId,
  roomId,
  bedId,
}: {
  propertyId: string;
  floorId: string;
  roomId: string;
  bedId: string;
}) {
  const property = mockProperties.find((p) => p.id === propertyId) || mockProperties[0];
  const floor = property.floors.find((f) => f.id === floorId) || property.floors[0] || { id: floorId, level: floorId, name: `Floor ${floorId}` };
  const room = floor.rooms?.find((r) => r.id === roomId) || { id: roomId, name: roomId, sharingType: "double", category: "ac", beds: [] };
  
  // Find bed or fall back to default
  const defaultBed: Bed = {
    id: bedId,
    name: `Bed ${bedId}`,
    status: "maintenance" as const,
    rackRate: "₹850.00",
    deposit: "₹400.00",
    maintenanceIssue: {
      id: "WO-4921",
      issue: "Reported broken bed frame slat. Scheduled for repair by internal team on 10/24/2023.",
      date: "10/21/2023",
      reporter: "Staff (J. Doe)"
    },
    history: [
      { resident: "Alex Smith", term: "Fall Semester '23", moveIn: "08/15/23", moveOut: "10/20/23 (Early)", rate: "₹850", initials: "AS" },
      { resident: "Maria Johnson", term: "Spring Semester '23", moveIn: "01/10/23", moveOut: "05/30/23", rate: "₹825", initials: "MJ" },
      { resident: "David Torres", term: "Fall Semester '22", moveIn: "08/12/22", moveOut: "12/15/22", rate: "₹800", initials: "DT" }
    ]
  };
  const bed = room.beds?.find((b) => b.id === bedId) || defaultBed;

  const [bedStatus, setBedStatus] = useState(bed.status);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const handleResolveMaintenance = () => {
    setBedStatus("available");
    setSuccessMsg("Maintenance issue resolved. Bed status is now set to Available.");
    setTimeout(() => setSuccessMsg(null), 4000);
  };

  const handleSetMaintenance = () => {
    setBedStatus("maintenance");
    setSuccessMsg("Bed status set to Maintenance. Occupant assignments are now restricted.");
    setTimeout(() => setSuccessMsg(null), 4000);
  };

  return (
    <div className="space-y-6">
      {/* Toast Alert */}
      {successMsg && (
        <div className="fixed bottom-5 right-5 z-50 flex items-center gap-3 rounded-xl border border-emerald-100 bg-emerald-50 p-4 text-emerald-800 shadow-xl animate-bounce max-w-sm">
          <CheckCircle2 className="size-5 text-emerald-600 shrink-0" />
          <div className="text-sm">
            <span className="font-semibold">Status Updated</span>
            <p className="text-xs text-emerald-700 mt-0.5">{successMsg}</p>
          </div>
        </div>
      )}

      {/* Header and Breadcrumbs */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          {/* Breadcrumbs */}
          <nav aria-label="Breadcrumb" className="flex items-center text-xs text-ink-muted mb-2">
            <ol className="inline-flex items-center space-x-1">
              <li>
                <Link href="/properties" className="hover:text-accent font-medium transition-colors">
                  Properties
                </Link>
              </li>
              <li className="flex items-center">
                <ChevronRight className="size-3 text-ink-faint mx-1" />
                <Link href={`/properties/${property.id}/floors`} className="hover:text-accent font-medium transition-colors">
                  {property.name}
                </Link>
              </li>
              <li className="flex items-center">
                <ChevronRight className="size-3 text-ink-faint mx-1" />
                <Link href={`/properties/${property.id}/floors/${floor.id}/rooms`} className="hover:text-accent font-medium transition-colors">
                  {floor.name}
                </Link>
              </li>
              <li className="flex items-center">
                <ChevronRight className="size-3 text-ink-faint mx-1" />
                <span className="text-ink font-semibold">Room {room.name}</span>
              </li>
            </ol>
          </nav>
          <h1 className="text-2xl font-bold tracking-tight text-ink md:text-3xl">Bed {room.name}-{bed.id}</h1>
        </div>

        {/* Resolve maintenance actions */}
        <div className="flex gap-2">
          {bedStatus === "maintenance" ? (
            <button
              onClick={handleResolveMaintenance}
              className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-border bg-surface-card px-4 py-2.5 text-xs font-bold text-ink hover:bg-surface-page cursor-pointer shadow-sm transition-colors"
            >
              <CheckCircle className="size-3.5 text-emerald-600" />
              Resolve Maintenance
            </button>
          ) : (
            <button
              onClick={handleSetMaintenance}
              className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-status-critical/30 bg-status-critical-soft px-4 py-2.5 text-xs font-bold text-status-critical hover:bg-status-critical hover:text-ink-inverse cursor-pointer transition-all"
            >
              <Wrench className="size-3.5" />
              Flag Maintenance
            </button>
          )}
        </div>
      </div>

      {/* Bento Layout Grid */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        {/* Left Card: Current Occupant */}
        <div className="lg:col-span-8 bg-surface-card border border-border rounded-2xl p-5 shadow-sm space-y-4">
          <h3 className="text-xs font-bold uppercase tracking-wider text-ink-faint border-b border-border pb-3">Current Occupant</h3>
          
          {bedStatus === "maintenance" ? (
            <div className="rounded-xl border-2 border-dashed border-border bg-surface-page/50 p-8 flex flex-col items-center justify-center text-center min-h-[180px]">
              <Wrench className="size-9 text-ink-faint mb-2.5" />
              <p className="text-sm font-semibold text-ink">Bed is currently unoccupied</p>
              <p className="text-xs text-ink-muted mt-0.5">Status set to Maintenance prevents admissions.</p>
            </div>
          ) : bedStatus === "occupied" ? (
            <div className="rounded-xl border border-border bg-surface-page/40 p-4.5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                <div className="size-11 rounded-full bg-accent-soft text-accent border border-accent/15 flex items-center justify-center font-bold text-base shadow-sm">
                  {bed.history[0]?.initials || "AS"}
                </div>
                <div>
                  <h4 className="text-sm font-bold text-ink">{bed.currentOccupant || "Alex Smith"}</h4>
                  <p className="text-xs text-ink-muted mt-0.5">Active lease contract · {bed.history[0]?.term || "Fall Semester '23"}</p>
                </div>
              </div>
              <div className="flex flex-col text-xs text-right space-y-0.5">
                <span className="font-semibold text-ink">Move-in date</span>
                <span className="font-mono text-ink-muted">{bed.history[0]?.moveIn || "08/15/23"}</span>
              </div>
            </div>
          ) : (
            <div className="rounded-xl border-2 border-dashed border-border bg-surface-page/50 p-8 flex flex-col items-center justify-center text-center min-h-[180px]">
              <User className="size-9 text-ink-faint mb-2.5" />
              <p className="text-sm font-semibold text-ink">Bed is empty & available</p>
              <p className="text-xs text-ink-muted mt-0.5">Ready for new tenant check-ins.</p>
              <Link
                href="/admissions"
                className="mt-4 rounded-xl bg-accent hover:bg-accent-hover text-ink-inverse text-xs font-semibold px-4 py-2 transition-colors cursor-pointer"
              >
                Allocate Bed
              </Link>
            </div>
          )}
        </div>

        {/* Right Card: Financials overview */}
        <div className="lg:col-span-4 bg-surface-card border border-border rounded-2xl p-5 shadow-sm space-y-4 flex flex-col justify-between">
          <h3 className="text-xs font-bold uppercase tracking-wider text-ink-faint border-b border-border pb-3">Financial Overview</h3>
          <div className="space-y-3.5 text-sm">
            <div className="flex justify-between items-center pb-2 border-b border-border/40">
              <span className="text-ink-muted">Rack Rate (Monthly)</span>
              <span className="font-mono font-semibold text-ink">{bed.rackRate}</span>
            </div>
            <div className="flex justify-between items-center pb-2 border-b border-border/40">
              <span className="text-ink-muted">Current Override</span>
              <span className="font-mono font-semibold text-ink">--</span>
            </div>
            <div className="flex justify-between items-center pb-2 border-b border-border/40">
              <span className="text-ink-muted">Deposit Requirement</span>
              <span className="font-mono font-semibold text-ink">{bed.deposit}</span>
            </div>
            <div className="pt-2.5 flex justify-between items-center font-bold">
              <span className="text-ink">Projected Rev</span>
              <span className={`font-mono ${bedStatus === "occupied" ? "text-emerald-600" : "text-status-critical"}`}>
                {bedStatus === "occupied" ? bed.rackRate : "₹0.00"} / mo
              </span>
            </div>
          </div>
        </div>

        {/* Bottom Card 1: Maintenance issue details banner */}
        {bedStatus === "maintenance" && bed.maintenanceIssue && (
          <div className="lg:col-span-12 rounded-2xl bg-status-critical-soft border border-status-critical/15 p-5 shadow-sm">
            <div className="flex items-start gap-4">
              <div className="bg-status-critical text-white p-2.5 rounded-full shadow-sm shrink-0">
                <Wrench className="size-5" />
              </div>
              <div className="space-y-2">
                <h4 className="text-sm font-bold text-ink flex items-center gap-1.5">
                  Active Maintenance Work Order #{bed.maintenanceIssue.id}
                </h4>
                <p className="text-xs text-ink-muted leading-relaxed max-w-2xl">{bed.maintenanceIssue.issue}</p>
                <div className="flex flex-wrap gap-x-6 gap-y-1.5 pt-1 text-[10px] text-ink-faint uppercase font-bold">
                  <span className="flex items-center gap-1">
                    <Calendar className="size-3 text-ink-faint" /> Reported: {bed.maintenanceIssue.date}
                  </span>
                  <span className="flex items-center gap-1">
                    <User className="size-3 text-ink-faint" /> Reporter: {bed.maintenanceIssue.reporter}
                  </span>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Bottom Card 2: Occupant History table */}
        <div className="lg:col-span-12 bg-surface-card border border-border rounded-2xl overflow-hidden shadow-sm">
          <div className="px-5 py-4 border-b border-border flex justify-between items-center">
            <h3 className="text-xs font-bold uppercase tracking-wider text-ink-faint">Occupant Lease History</h3>
            <button className="text-xs font-bold text-accent hover:underline cursor-pointer">
              View Full History
            </button>
          </div>
          <div className="overflow-x-auto text-xs">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="bg-surface-page font-semibold text-ink-muted border-b border-border">
                  <th className="px-5 py-2.5">Resident</th>
                  <th className="px-5 py-2.5">Lease Term</th>
                  <th className="px-5 py-2.5">Move-In</th>
                  <th className="px-5 py-2.5">Move-Out</th>
                  <th className="px-5 py-2.5 text-right">Contracted Rate</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border text-ink">
                {bed.history.map((row, idx) => (
                  <tr key={idx} className="hover:bg-surface-page/35">
                    <td className="px-5 py-3 flex items-center gap-2.5">
                      <div className="size-6 rounded-full bg-slate-100 border border-border text-[9px] font-bold text-slate-800 flex items-center justify-center shrink-0">
                        {row.initials}
                      </div>
                      <span className="font-semibold">{row.resident}</span>
                    </td>
                    <td className="px-5 py-3 text-ink-muted">{row.term}</td>
                    <td className="px-5 py-3 font-mono text-ink-muted">{row.moveIn}</td>
                    <td className="px-5 py-3 font-mono text-ink-muted">{row.moveOut}</td>
                    <td className="px-5 py-3 font-mono text-right font-semibold">{row.rate}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
