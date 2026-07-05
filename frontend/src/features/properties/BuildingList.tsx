"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { ChevronRight, Plus, Trash2, Building2, Settings, LoaderCircle, AlertTriangle } from "lucide-react";
import { getProperty, listBuildings, deleteBuilding, type Property, type Building, ApiError } from "@/lib/api";

export function BuildingList({ propertyId }: { propertyId: string }) {
  const [property, setProperty] = useState<Property | null>(null);
  const [buildings, setBuildings] = useState<Building[] | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const [deleteAlert, setDeleteAlert] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    Promise.all([getProperty(propertyId), listBuildings(propertyId)])
      .then(([propData, buildingsData]) => {
        if (cancelled) return;
        setProperty(propData);
        setBuildings(buildingsData.sort((a, b) => a.order - b.order));
        setIsLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        console.error(err);
        setError(err instanceof ApiError ? err.message : "Failed to load buildings. Please try again.");
        setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [propertyId]);

  const handleDeleteBuilding = async (buildingId: string, name: string) => {
    try {
      await deleteBuilding(buildingId);
      setBuildings((prev) => (prev ? prev.filter((b) => b.id !== buildingId) : null));
      setDeleteAlert(`Building "${name}" removed from property.`);
      setTimeout(() => setDeleteAlert(null), 3000);
    } catch (err) {
      console.error(err);
      alert(err instanceof ApiError ? err.message : "Failed to delete building.");
    }
  };

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-32 text-sm text-ink-muted">
        <LoaderCircle className="size-8 animate-spin text-accent" />
        <p className="font-semibold mt-2">Loading buildings...</p>
      </div>
    );
  }

  if (error || !property || !buildings) {
    return (
      <div className="space-y-4 max-w-md mx-auto py-16 text-center">
        <div className="flex size-14 items-center justify-center rounded-full bg-status-critical-soft text-status-critical border border-status-critical/10 mx-auto">
          <AlertTriangle className="size-6" />
        </div>
        <h3 className="text-lg font-bold text-ink">Failed to Load Buildings</h3>
        <p className="text-xs text-ink-muted leading-relaxed">
          {error || "Could not retrieve property metadata."}
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

  return (
    <div className="space-y-6">
      {deleteAlert && (
        <div className="fixed bottom-5 right-5 z-50 flex items-center gap-3 rounded-xl border border-red-100 bg-red-50 p-4 text-red-800 shadow-xl animate-bounce">
          <Trash2 className="size-5 text-red-600" />
          <div className="text-sm">
            <span className="font-semibold">Building Deleted</span>
            <p className="text-xs text-red-700">{deleteAlert}</p>
          </div>
        </div>
      )}

      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <nav aria-label="Breadcrumb" className="flex items-center text-xs text-ink-muted mb-2">
            <ol className="inline-flex items-center space-x-1">
              <li>
                <Link href="/properties" className="hover:text-accent font-medium transition-colors">
                  Properties
                </Link>
              </li>
              <li className="flex items-center">
                <ChevronRight className="size-3 text-ink-faint mx-1" />
                <span className="text-ink font-semibold">{property.name}</span>
              </li>
            </ol>
          </nav>

          <h1 className="text-2xl font-bold tracking-tight text-ink md:text-3xl">Buildings</h1>
          <p className="text-xs text-ink-muted mt-1">
            Most PGs are a single building — add more here if this property spans multiple blocks.
          </p>
        </div>

        <div className="flex gap-2.5 self-start sm:self-auto">
          <Link
            href={`/properties/${property.id}/settings`}
            className="inline-flex items-center justify-center gap-2 rounded-xl border border-border bg-surface-card px-4 py-2.5 text-sm font-semibold text-ink-muted hover:bg-surface-page active:scale-[0.98] transition-all cursor-pointer"
          >
            <Settings className="size-4" />
            Billing Settings
          </Link>
          <Link
            href={`/properties/${property.id}/buildings/add`}
            className="inline-flex items-center justify-center gap-2 rounded-xl bg-accent px-4 py-2.5 text-sm font-semibold text-ink-inverse hover:bg-accent-hover hover:shadow-lg hover:shadow-blue-500/10 active:scale-[0.98] transition-all cursor-pointer"
          >
            <Plus className="size-4.5" />
            Add Building
          </Link>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div className="rounded-xl border border-border bg-surface-card p-4.5 shadow-sm flex flex-col justify-between">
          <span className="text-xs font-bold text-ink-faint uppercase tracking-wider">Buildings</span>
          <span className="text-2xl font-extrabold tracking-tight text-ink mt-2">{buildings.length}</span>
        </div>
        <div className="rounded-xl border border-border bg-surface-card p-4.5 shadow-sm flex flex-col justify-between">
          <span className="text-xs font-bold text-ink-faint uppercase tracking-wider">Total Floors</span>
          <span className="text-2xl font-extrabold tracking-tight text-ink mt-2">{property.floors_count}</span>
        </div>
        <div className="rounded-xl border border-border bg-surface-card p-4.5 shadow-sm flex flex-col justify-between col-span-2">
          <span className="text-xs font-bold text-ink-faint uppercase tracking-wider">Property Occupancy</span>
          <div className="flex items-center gap-4 mt-2.5">
            <span className="text-2xl font-extrabold text-accent">{property.occupancy_percent}%</span>
            <div className="flex-grow h-2 bg-surface-page rounded-full overflow-hidden border border-border">
              <div className="h-full bg-accent rounded-full" style={{ width: `${property.occupancy_percent}%` }} />
            </div>
          </div>
        </div>
      </div>

      <div className="rounded-2xl border border-border bg-surface-card shadow-sm overflow-hidden">
        <div className="hidden md:grid grid-cols-12 gap-4 px-6 py-3 bg-surface-page border-b border-border font-bold text-xs text-ink-muted uppercase tracking-wider items-center">
          <div className="col-span-4">Building</div>
          <div className="col-span-2 text-right pr-6">Floors</div>
          <div className="col-span-4">Occupancy Status</div>
          <div className="col-span-2 text-right">Actions</div>
        </div>

        {buildings.length > 0 ? (
          <div className="divide-y divide-border">
            {buildings.map((building) => (
              <div
                key={building.id}
                className="grid grid-cols-1 md:grid-cols-12 gap-4 items-center px-6 py-4.5 hover:bg-surface-page/40 transition-colors group"
              >
                <div className="col-span-1 md:col-span-4 flex items-center gap-3">
                  <div className="size-10 rounded-full bg-surface-page flex items-center justify-center font-mono text-xs font-bold text-ink border border-border shrink-0">
                    <Building2 className="size-4.5" />
                  </div>
                  <div>
                    <Link
                      href={`/properties/${property.id}/buildings/${building.id}/floors`}
                      className="text-sm font-semibold text-ink hover:text-accent transition-colors"
                    >
                      {building.name}
                    </Link>
                    <p className="text-xs text-ink-muted md:hidden mt-0.5">
                      {building.floors_count} Floors · {building.occupancy_percent}% Occupied
                    </p>
                  </div>
                </div>

                <div className="hidden md:block col-span-2 font-mono text-xs font-semibold text-ink text-right pr-6">
                  {String(building.floors_count).padStart(2, "0")}
                </div>

                <div className="hidden md:flex col-span-4 items-center gap-4 pr-6">
                  <div className="flex-grow h-1.5 rounded-full bg-surface-page border border-border overflow-hidden">
                    <div
                      className={`h-full rounded-full ${
                        building.occupancy_percent === 100 ? "bg-surface-inverse" : "bg-accent"
                      }`}
                      style={{ width: `${building.occupancy_percent}%` }}
                    />
                  </div>
                  <span className="font-mono text-xs font-semibold text-ink-muted w-10 text-right">
                    {building.occupancy_percent}%
                  </span>
                </div>

                <div className="col-span-1 md:col-span-2 flex justify-end gap-2.5 pt-3.5 md:pt-0 border-t md:border-none border-border/40">
                  <button
                    onClick={() => handleDeleteBuilding(building.id, building.name)}
                    aria-label="Delete Building"
                    className="p-1.5 text-ink-muted hover:text-status-critical hover:bg-status-critical-soft rounded-lg transition-colors cursor-pointer"
                  >
                    <Trash2 className="size-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center text-center p-12 space-y-4 bg-surface-card">
            <div className="flex size-14 items-center justify-center rounded-full bg-surface-page text-ink-muted border border-border">
              <Building2 className="size-6 text-ink-faint animate-pulse" />
            </div>
            <div className="space-y-1 max-w-sm">
              <h3 className="text-sm font-bold text-ink">No Buildings Configured</h3>
              <p className="text-xs text-ink-muted leading-relaxed">
                This property does not have any buildings configured yet. Click Add Building to begin.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
