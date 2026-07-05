"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { Plus, MapPin, Building, ChevronRight, LoaderCircle, AlertTriangle, Pencil } from "lucide-react";
import { ApiError, listProperties, type Property } from "@/lib/api";

const PROPERTY_TYPE_LABELS: Record<string, string> = {
  pg: "PG (Paying Guest)",
  boys_hostel: "Boys Hostel",
  girls_hostel: "Girls Hostel",
  co_living: "Co-Living Space",
};

export function PropertyList() {
  const [properties, setProperties] = useState<Property[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    listProperties()
      .then((data) => {
        if (!cancelled) setProperties(data);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Could not reach the server. Please try again.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

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

      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-status-critical/30 bg-status-critical-soft px-4 py-3 text-sm text-status-critical">
          <AlertTriangle className="size-4 shrink-0" />
          {error}
        </div>
      )}

      {!error && properties === null && (
        <div className="flex items-center justify-center gap-2 py-16 text-sm text-ink-muted">
          <LoaderCircle className="size-4.5 animate-spin" />
          Loading properties...
        </div>
      )}

      {!error && properties !== null && properties.length === 0 && (
        <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-border py-16 text-center">
          <Building className="size-8 text-ink-faint" />
          <p className="text-sm font-semibold text-ink">No properties registered yet</p>
          <p className="text-xs text-ink-muted">Add your first property to start building its floor and bed hierarchy.</p>
        </div>
      )}

      {/* Grid List */}
      {properties && properties.length > 0 && (
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        {properties.map((property) => (
          <div
            key={property.id}
            className="bg-surface-card border border-border rounded-2xl overflow-hidden shadow-sm flex flex-col justify-between hover:shadow-md transition-shadow"
          >
            {/* Visual Thumbnail */}
            <div className="relative h-48 w-full bg-slate-900 overflow-hidden">
              {property.images && property.images.length > 0 ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={property.images[0].image}
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
                  {PROPERTY_TYPE_LABELS[property.property_type] ?? property.property_type}
                </span>
              </div>
              {/* Edit action overlay */}
              <Link
                href={`/properties/${property.id}/edit`}
                className="absolute top-4 right-4 z-10 inline-flex items-center gap-1.5 bg-slate-950/50 backdrop-blur-md text-white border border-white/20 px-3 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider hover:bg-slate-950/70 transition-colors cursor-pointer"
              >
                <Pencil className="size-3" />
                Edit
              </Link>
            </div>

            {/* Property details */}
            <div className="p-5 space-y-4">
              <div>
                <h3 className="text-lg font-bold text-ink hover:text-accent transition-colors">
                  <Link href={`/properties/${property.id}/buildings`}>{property.name}</Link>
                </h3>
                <p className="text-xs text-ink-muted mt-1 flex items-center gap-1.5">
                  <MapPin className="size-3.5 text-ink-faint shrink-0" />
                  {property.address_line}, {property.city}, {property.state}
                </p>
              </div>

              {/* Metrics */}
              <div className="grid grid-cols-3 gap-3.5 bg-surface-page p-3 rounded-xl border border-border/60 text-xs">
                <div className="flex flex-col">
                  <span className="text-ink-faint uppercase font-bold text-[10px] tracking-wide">Levels</span>
                  <span className="font-semibold text-ink mt-0.5">{property.floors_count} Floors</span>
                </div>
                <div className="flex flex-col">
                  <span className="text-ink-faint uppercase font-bold text-[10px] tracking-wide">Capacity</span>
                  <span className="font-semibold text-ink mt-0.5">{property.rooms_count} Rooms</span>
                </div>
                <div className="flex flex-col">
                  <span className="text-ink-faint uppercase font-bold text-[10px] tracking-wide">Beds</span>
                  <span className="font-semibold text-ink mt-0.5">{property.beds_count} Beds</span>
                </div>
              </div>
            </div>

            {/* Footer Action link */}
            <div className="px-5 py-3.5 bg-surface-page/30 border-t border-border flex justify-end">
              <Link
                href={`/properties/${property.id}/buildings`}
                className="text-xs font-bold text-accent hover:text-accent-hover transition-colors inline-flex items-center gap-1 cursor-pointer"
              >
                Manage Layout
                <ChevronRight className="size-4" />
              </Link>
            </div>
          </div>
        ))}
      </div>
      )}
    </div>
  );
}
