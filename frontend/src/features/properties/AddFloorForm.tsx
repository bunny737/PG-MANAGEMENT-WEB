"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Landmark, Eye, CheckCircle2 } from "lucide-react";
import { mockProperties } from "./mock-properties";

export function AddFloorForm({ propertyId }: { propertyId: string }) {
  const router = useRouter();
  const property = mockProperties.find((p) => p.id === propertyId) || mockProperties[0];

  const [building, setBuilding] = useState(property.id);
  const [floorId, setFloorId] = useState("");
  const [totalRooms, setTotalRooms] = useState("");

  const [isLoading, setIsLoading] = useState(false);
  const [showSuccess, setShowSuccess] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const handleFormSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const newErrors: Record<string, string> = {};

    if (!building) newErrors.building = "Building Name is required";
    if (!floorId) newErrors.floorId = "Floor ID is required";

    if (Object.keys(newErrors).length > 0) {
      setErrors(newErrors);
      return;
    }

    setErrors({});
    setIsLoading(true);

    setTimeout(() => {
      setIsLoading(false);
      setShowSuccess(true);
    }, 1200);
  };

  const handleCloseModal = () => {
    setShowSuccess(false);
    router.push(`/properties/${property.id}/floors`);
  };

  return (
    <div className="space-y-6 max-w-md mx-auto">
      {/* Success Modal Backdrop */}
      {showSuccess && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-6 bg-on-surface/40 backdrop-blur-sm transition-opacity duration-300">
          <div className="bg-surface-container-lowest p-8 rounded-2xl max-w-sm w-full text-center shadow-2xl border border-border">
            <div className="size-20 bg-blue-50 text-accent border border-blue-100 rounded-full flex items-center justify-center mx-auto mb-6">
              <CheckCircle2 className="size-10" />
            </div>
            <h3 className="text-xl font-bold text-ink mb-2">Floor Created</h3>
            <p className="text-xs text-ink-muted mb-8 leading-relaxed">
              Building hierarchy has been updated successfully. You can now assign units to this floor level.
            </p>
            <button
              onClick={handleCloseModal}
              className="w-full py-3 bg-surface-inverse text-ink-inverse font-bold rounded-xl hover:opacity-90 transition-opacity cursor-pointer text-sm"
            >
              Back to Floor List
            </button>
          </div>
        </div>
      )}

      {/* Header */}
      <div className="flex items-center gap-3">
        <Link
          href={`/properties/${property.id}/floors`}
          className="hover:bg-surface-page p-2 rounded-full transition-colors inline-flex items-center justify-center border border-border"
        >
          <ArrowLeft className="size-5 text-ink-muted" />
        </Link>
        <div>
          <h1 className="text-xl font-bold tracking-tight text-ink">Add Floor</h1>
          <p className="text-xs text-ink-muted">Create a new level under the selected building.</p>
        </div>
      </div>

      {/* Bento Context Card */}
      <div className="bg-surface-card p-5 rounded-2xl border border-border shadow-sm flex items-start gap-4">
        <div className="size-11 rounded-lg bg-accent-soft text-accent border border-accent/15 flex items-center justify-center shrink-0">
          <Landmark className="size-5.5" />
        </div>
        <div className="space-y-0.5 text-xs">
          <p className="font-bold text-accent uppercase tracking-wider">Property Management</p>
          <h2 className="text-sm font-bold text-ink">Floor Registration</h2>
          <p className="text-ink-muted leading-relaxed mt-1">Expanding your building&apos;s vertical capacity and inventory.</p>
        </div>
      </div>

      {/* Form Fields */}
      <form onSubmit={handleFormSubmit} className="space-y-5">
        {/* Building Select dropdown */}
        <div className="space-y-1.5">
          <label htmlFor="building" className="text-xs font-semibold uppercase tracking-wider text-ink-muted ml-1">
            Building Name <span className="text-status-critical">*</span>
          </label>
          <select
            id="building"
            value={building}
            onChange={(e) => setBuilding(e.target.value)}
            className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2.5 text-sm text-ink-muted outline-none transition-all focus:ring-4 focus:ring-accent/15 focus:border-accent"
            disabled={isLoading}
          >
            <option value="skyline">Skyline Tower</option>
            <option value="sunset">Sunset Apartments Complex</option>
          </select>
        </div>

        {/* Floor ID & Rooms grid */}
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <label htmlFor="floor_id" className="text-xs font-semibold uppercase tracking-wider text-ink-muted ml-1">
              Floor ID <span className="text-status-critical">*</span>
            </label>
            <input
              id="floor_id"
              type="text"
              placeholder="e.g. 14, Penthouse"
              value={floorId}
              onChange={(e) => setFloorId(e.target.value)}
              className={`w-full rounded-xl border ${
                errors.floorId ? "border-status-critical focus:ring-status-critical/10" : "border-border focus:ring-accent/15 focus:border-accent"
              } bg-surface-card px-4 py-2.5 text-sm text-ink outline-none transition-all focus:ring-4`}
              disabled={isLoading}
            />
            {errors.floorId && <p className="text-xs text-status-critical">{errors.floorId}</p>}
          </div>

          <div className="space-y-1.5">
            <label htmlFor="total_rooms" className="text-xs font-semibold uppercase tracking-wider text-ink-muted ml-1">
              Rooms Count
            </label>
            <input
              id="total_rooms"
              type="number"
              min="0"
              placeholder="0"
              value={totalRooms}
              onChange={(e) => setTotalRooms(e.target.value)}
              className="w-full rounded-xl border border-border bg-surface-card px-4 py-2.5 text-sm text-ink outline-none transition-all focus:ring-4 focus:ring-accent/15 focus:border-accent"
              disabled={isLoading}
            />
          </div>
        </div>

        {/* Blueprint Visual Preview Area */}
        <div className="relative h-44 w-full rounded-2xl overflow-hidden border border-border group bg-slate-900">
          <div className="absolute inset-0 bg-gradient-to-t from-slate-950/60 to-transparent z-10" />
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            alt="Floor Blueprint"
            src="https://lh3.googleusercontent.com/aida-public/AB6AXuCpmXRPgbatfIpR-cLRxt_weqLuH1S0ZeGPx1n6F8yzzpnZsLaLD5Wz4ESovxH_hXJ6ZOS65wU3vJdyCnQcIT-InQx6wxGs7AU6sdscXep7aA7l4h_NM3ug--SVKOEGJd8KvaJvJqwVV--4fUvdWoc83PBrLWev3a2FnP4RnlHtvgkdbMMygXpnRrcLHwlNUlaZRhQeN7rRCF9Xc2Saw2eLvNlOTTfAeFCNyqAbqiAy5FH4VMHggvg8Sw"
            className="size-full object-cover group-hover:scale-105 transition-transform duration-700 opacity-80"
          />
          <div className="absolute bottom-4 left-4 z-20">
            <div className="flex items-center gap-1.5 bg-slate-950/40 backdrop-blur-md px-3 py-1 rounded-full border border-white/20">
              <Eye className="size-3.5 text-white" />
              <span className="text-[10px] font-bold text-white uppercase tracking-wider">Preview Blueprint</span>
            </div>
          </div>
        </div>

        <p className="text-center text-[10px] text-ink-muted">
          Creating a floor level will automatically log an entry in the Audit timeline.
        </p>

        {/* Action Button */}
        <button
          type="submit"
          disabled={isLoading}
          className="w-full bg-accent text-ink-inverse hover:bg-accent-hover font-semibold py-3 px-6 rounded-xl flex items-center justify-center gap-2 cursor-pointer transition-colors shadow-sm disabled:opacity-50"
        >
          {isLoading ? "Creating Floor..." : "Add Floor"}
        </button>
      </form>
    </div>
  );
}
