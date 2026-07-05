"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { ChevronRight, Wrench, CheckCircle, User, Calendar, CheckCircle2, LoaderCircle, AlertTriangle } from "lucide-react";
import { getProperty, getFloor, getRoom, getBed, updateBed, type Property, type Floor, type Room, type Bed, ApiError } from "@/lib/api";

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
  const [property, setProperty] = useState<Property | null>(null);
  const [floor, setFloor] = useState<Floor | null>(null);
  const [room, setRoom] = useState<Room | null>(null);
  const [bed, setBed] = useState<Bed | null>(null);
  const [bedStatus, setBedStatus] = useState<string>("available");

  const [isLoading, setIsLoading] = useState(true);
  const [isUpdating, setIsUpdating] = useState(false);
  const [error, setError] = useState("");
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Track propertyId / floorId / roomId / bedId changes to reset loading state (React render-time adjustment pattern)
  const [prevIds, setPrevIds] = useState({ propertyId, floorId, roomId, bedId });
  if (propertyId !== prevIds.propertyId || floorId !== prevIds.floorId || roomId !== prevIds.roomId || bedId !== prevIds.bedId) {
    setPrevIds({ propertyId, floorId, roomId, bedId });
    setIsLoading(true);
    setError("");
  }

  useEffect(() => {
    let cancelled = false;

    Promise.all([
      getProperty(propertyId),
      getFloor(floorId),
      getRoom(roomId),
      getBed(bedId)
    ])
      .then(([propData, floorData, roomData, bedData]) => {
        if (cancelled) return;
        setProperty(propData);
        setFloor(floorData);
        setRoom(roomData);
        setBed(bedData);
        setBedStatus(bedData.status);
        setIsLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        console.error(err);
        setError(err instanceof ApiError ? err.message : "Failed to load bed details. Please try again.");
        setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [propertyId, floorId, roomId, bedId]);

  const handleResolveMaintenance = async () => {
    setIsUpdating(true);
    try {
      const updated = await updateBed(bedId, { status: "available" });
      setBed(updated);
      setBedStatus(updated.status);
      setSuccessMsg("Maintenance issue resolved. Bed status is now set to Available.");
      setTimeout(() => setSuccessMsg(null), 4000);
    } catch (err) {
      console.error(err);
      alert("Failed to resolve maintenance: " + (err instanceof ApiError ? err.message : "Error"));
    } finally {
      setIsUpdating(false);
    }
  };

  const handleSetMaintenance = async () => {
    setIsUpdating(true);
    try {
      const updated = await updateBed(bedId, { status: "maintenance" });
      setBed(updated);
      setBedStatus(updated.status);
      setSuccessMsg("Bed status set to Maintenance. Occupant assignments are now restricted.");
      setTimeout(() => setSuccessMsg(null), 4000);
    } catch (err) {
      console.error(err);
      alert("Failed to flag maintenance: " + (err instanceof ApiError ? err.message : "Error"));
    } finally {
      setIsUpdating(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-32 text-sm text-ink-muted">
        <LoaderCircle className="size-8 animate-spin text-accent" />
        <p className="font-semibold mt-2">Loading bed details...</p>
      </div>
    );
  }

  if (error || !property || !floor || !room || !bed) {
    return (
      <div className="space-y-4 max-w-md mx-auto py-16 text-center">
        <div className="flex size-14 items-center justify-center rounded-full bg-status-critical-soft text-status-critical border border-status-critical/10 mx-auto">
          <AlertTriangle className="size-6" />
        </div>
        <h3 className="text-lg font-bold text-ink">Failed to Load Bed Details</h3>
        <p className="text-xs text-ink-muted leading-relaxed">
          {error || "Could not retrieve bed layout data."}
        </p>
        <button
          onClick={() => window.location.reload()}
          className="px-4 py-2 bg-surface-inverse text-ink-inverse text-xs font-semibold rounded-xl hover:opacity-90 transition-opacity cursor-pointer shadow-sm"
        >
          Retry
        </button>
      </div>
    );
  }

  const hasFoodOverride = bed.rack_rate_with_food_override !== null;
  const hasNoFoodOverride = bed.rack_rate_without_food_override !== null;

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
                <span className="text-ink font-semibold">Room {room.room_number}</span>
              </li>
            </ol>
          </nav>
          <h1 className="text-2xl font-bold tracking-tight text-ink md:text-3xl">Bed {bed.bed_number}</h1>
        </div>

        {/* Resolve maintenance actions */}
        <div className="flex gap-2">
          {bedStatus === "maintenance" ? (
            <button
              onClick={handleResolveMaintenance}
              disabled={isUpdating}
              className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-border bg-surface-card px-4 py-2.5 text-xs font-bold text-ink hover:bg-surface-page cursor-pointer shadow-sm transition-colors disabled:opacity-50"
            >
              <CheckCircle className="size-3.5 text-emerald-600" />
              Resolve Maintenance
            </button>
          ) : (
            <button
              onClick={handleSetMaintenance}
              disabled={isUpdating}
              className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-status-critical/30 bg-status-critical-soft px-4 py-2.5 text-xs font-bold text-status-critical hover:bg-status-critical hover:text-ink-inverse cursor-pointer transition-all disabled:opacity-50"
            >
              <Wrench className="size-3.5" />
              Flag Maintenance
            </button>
          )}
        </div>
      </div>

      {/* Bed Selector Switcher */}
      {room.beds && room.beds.length > 1 && (
        <div className="flex flex-wrap gap-2 pb-2">
          {room.beds.map((b) => {
            const isActive = b.id === bedId;
            return (
              <Link
                key={b.id}
                href={`/properties/${propertyId}/floors/${floorId}/rooms/${roomId}/beds/${b.id}`}
                className={`rounded-xl px-4 py-2 text-xs font-bold border transition-all cursor-pointer ${
                  isActive
                    ? "bg-surface-inverse text-ink-inverse border-surface-inverse shadow-sm"
                    : "bg-surface-card text-ink-muted border-border hover:bg-surface-page hover:text-ink"
                }`}
              >
                Bed {b.bed_number}
              </Link>
            );
          })}
        </div>
      )}

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
          ) : bedStatus === "occupied" && bed.current_occupant ? (
            <div className="rounded-xl border border-border bg-surface-page/40 p-4.5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                <div className="size-11 rounded-full bg-accent-soft text-accent border border-accent/15 flex items-center justify-center font-bold text-base shadow-sm">
                  {bed.current_occupant.initials}
                </div>
                <div>
                  <h4 className="text-sm font-bold text-ink">{bed.current_occupant.full_name}</h4>
                  <p className="text-xs text-ink-muted mt-0.5 flex flex-col gap-0.5">
                    <span>Email: {bed.current_occupant.email || "--"}</span>
                    <span>Phone: {bed.current_occupant.phone || "--"}</span>
                  </p>
                </div>
              </div>
              <div className="flex flex-col text-xs text-left sm:text-right space-y-0.5">
                <span className="font-semibold text-ink">Move-in date</span>
                <span className="font-mono text-ink-muted">{bed.current_occupant.joining_date}</span>
                <span className="font-bold text-emerald-600 mt-1">Contract Rent: ₹{parseFloat(bed.current_occupant.rent).toFixed(2)}</span>
              </div>
            </div>
          ) : (
            <div className="rounded-xl border-2 border-dashed border-border bg-surface-page/50 p-8 flex flex-col items-center justify-center text-center min-h-[180px]">
              <User className="size-9 text-ink-faint mb-2.5" />
              <p className="text-sm font-semibold text-ink">Bed is empty & available</p>
              <p className="text-xs text-ink-muted mt-0.5">Ready for new tenant check-ins.</p>
              <Link
                href="/residents"
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
          <div className="space-y-3 text-sm">
            <div className="flex justify-between items-center pb-2 border-b border-border/40">
              <span className="text-ink-muted">Rate (With Food)</span>
              <span className="font-mono font-semibold text-ink">₹{parseFloat(bed.effective_rate_with_food).toFixed(2)}</span>
            </div>
            <div className="flex justify-between items-center pb-2 border-b border-border/40">
              <span className="text-ink-muted">Rate (Without Food)</span>
              <span className="font-mono font-semibold text-ink">₹{parseFloat(bed.effective_rate_without_food).toFixed(2)}</span>
            </div>
            <div className="flex justify-between items-center pb-2 border-b border-border/40">
              <span className="text-ink-muted">Active Override</span>
              <span className="font-mono font-semibold text-ink">
                {hasFoodOverride || hasNoFoodOverride ? "Yes" : "--"}
              </span>
            </div>
            <div className="pt-2.5 flex justify-between items-center font-bold">
              <span className="text-ink">Projected Rev</span>
              <span className={`font-mono ${bedStatus === "occupied" ? "text-emerald-600" : "text-status-critical"}`}>
                ₹{bedStatus === "occupied" 
                  ? parseFloat(bed.effective_rate_with_food).toFixed(2) 
                  : "0.00"} / mo
              </span>
            </div>
          </div>
        </div>

        {/* Bottom Card 1: Maintenance issue details banner */}
        {bedStatus === "maintenance" && (
          <div className="lg:col-span-12 rounded-2xl bg-status-critical-soft border border-status-critical/15 p-5 shadow-sm">
            <div className="flex items-start gap-4">
              <div className="bg-status-critical text-white p-2.5 rounded-full shadow-sm shrink-0">
                <Wrench className="size-5" />
              </div>
              <div className="space-y-2">
                <h4 className="text-sm font-bold text-ink flex items-center gap-1.5">
                  Unit Under Active Maintenance
                </h4>
                <p className="text-xs text-ink-muted leading-relaxed max-w-2xl">
                  This bed slot has been marked as under maintenance. Admitting residents is disabled until the issue is marked resolved.
                </p>
                <div className="flex flex-wrap gap-x-6 gap-y-1.5 pt-1 text-[10px] text-ink-faint uppercase font-bold">
                  <span className="flex items-center gap-1">
                    <Calendar className="size-3 text-ink-faint" /> Status: Maintenance
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
          </div>
          <div className="overflow-x-auto text-xs">
            {bed.history && bed.history.length > 0 ? (
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
            ) : (
              <div className="p-8 text-center text-ink-muted">
                No occupant lease history registered for this bed slot.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
