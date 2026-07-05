"use client";

import React from "react";
import Link from "next/link";
import { Plus, MapPin, Building, ChevronRight } from "lucide-react";
import { mockProperties } from "./mock-properties";

export function PropertyList() {
  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-ink md:text-3xl font-display-lg">Properties Portfolio</h1>
          <p className="mt-1 text-sm text-ink-muted">
            Manage your real estate assets, building hierarchies, floor layouts, and bed grids.
          </p>
        </div>
        <Link
          href="/properties/add"
          className="inline-flex items-center justify-center gap-2 rounded-xl bg-accent px-4 py-2.5 text-sm font-semibold text-ink-inverse hover:bg-accent-hover hover:shadow-lg hover:shadow-blue-500/10 active:scale-[0.98] transition-all cursor-pointer self-start sm:self-auto"
        >
          <Plus className="size-4.5" />
          Add Property
        </Link>
      </div>

      {/* Grid List */}
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        {mockProperties.map((property) => (
          <div
            key={property.id}
            className="bg-surface-card border border-border rounded-2xl overflow-hidden shadow-sm flex flex-col justify-between hover:shadow-md transition-shadow"
          >
            {/* Visual Thumbnail */}
            <div className="relative h-48 w-full bg-slate-900 overflow-hidden">
              {property.images && property.images.length > 0 ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={property.images[0]}
                  alt={property.name}
                  className="size-full object-cover opacity-95 hover:scale-105 transition-transform duration-700"
                />
              ) : (
                <div className="size-full flex flex-col items-center justify-center text-ink-faint gap-2">
                  <Building className="size-10 text-slate-700" />
                  <span className="text-xs uppercase tracking-wider text-slate-500 font-bold">No photo uploaded</span>
                </div>
              )}
              {/* Type pill overlay */}
              <div className="absolute top-4 left-4 z-10">
                <span className="bg-slate-950/50 backdrop-blur-md text-white border border-white/20 px-3 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider">
                  {property.type}
                </span>
              </div>
            </div>

            {/* Property details */}
            <div className="p-5 space-y-4">
              <div>
                <h3 className="text-lg font-bold text-ink hover:text-accent transition-colors">
                  <Link href={`/properties/${property.id}/floors`}>{property.name}</Link>
                </h3>
                <p className="text-xs text-ink-muted mt-1 flex items-center gap-1.5">
                  <MapPin className="size-3.5 text-ink-faint shrink-0" />
                  {property.address}, {property.city}, {property.state}
                </p>
              </div>

              {/* Metrics */}
              <div className="grid grid-cols-2 gap-3.5 bg-surface-page p-3 rounded-xl border border-border/60 text-xs">
                <div className="flex flex-col">
                  <span className="text-ink-faint uppercase font-bold text-[10px] tracking-wide">Capacity</span>
                  <span className="font-semibold text-ink mt-0.5">{property.totalRooms} Rooms</span>
                </div>
                <div className="flex flex-col">
                  <span className="text-ink-faint uppercase font-bold text-[10px] tracking-wide">Levels</span>
                  <span className="font-semibold text-ink mt-0.5">{property.totalFloors} Floors</span>
                </div>
              </div>

              {/* Occupancy bar */}
              <div className="space-y-1">
                <div className="flex justify-between items-baseline text-xs">
                  <span className="text-ink-muted font-medium">Occupancy percentage</span>
                  <span className="font-bold text-accent">{property.occupancyPercent}%</span>
                </div>
                <div className="h-1.5 w-full bg-surface-page rounded-full overflow-hidden border border-border">
                  <div className="h-full bg-accent rounded-full" style={{ width: `${property.occupancyPercent}%` }} />
                </div>
              </div>
            </div>

            {/* Footer Action link */}
            <div className="px-5 py-3.5 bg-surface-page/30 border-t border-border flex justify-end">
              <Link
                href={`/properties/${property.id}/floors`}
                className="text-xs font-bold text-accent hover:text-accent-hover transition-colors inline-flex items-center gap-1 cursor-pointer"
              >
                Manage Layout
                <ChevronRight className="size-4" />
              </Link>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
