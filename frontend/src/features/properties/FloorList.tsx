"use client";

import React, { useState } from "react";
import Link from "next/link";
import { ChevronRight, Plus, Trash2, Edit, Building2 } from "lucide-react";
import { mockProperties } from "./mock-properties";

export function FloorList({ propertyId }: { propertyId: string }) {
  const property = mockProperties.find((p) => p.id === propertyId) || mockProperties[0];

  const [floors, setFloors] = useState(property.floors);
  const [deleteAlert, setDeleteAlert] = useState<string | null>(null);

  const handleDeleteFloor = (floorId: string, level: string) => {
    setFloors(floors.filter((f) => f.id !== floorId));
    setDeleteAlert(`Floor ${level} removed from building inventory.`);
    setTimeout(() => setDeleteAlert(null), 3000);
  };

  return (
    <div className="space-y-6">
      {/* Alert toast for deletions */}
      {deleteAlert && (
        <div className="fixed bottom-5 right-5 z-50 flex items-center gap-3 rounded-xl border border-red-100 bg-red-50 p-4 text-red-800 shadow-xl animate-bounce">
          <Trash2 className="size-5 text-red-600" />
          <div className="text-sm">
            <span className="font-semibold">Floor Deleted</span>
            <p className="text-xs text-red-700">{deleteAlert}</p>
          </div>
        </div>
      )}

      {/* Breadcrumb and Add button header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          {/* Breadcrumb */}
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

          <h1 className="text-2xl font-bold tracking-tight text-ink md:text-3xl">Floor Management</h1>
        </div>

        <Link
          href={`/properties/${property.id}/floors/add`}
          className="inline-flex items-center justify-center gap-2 rounded-xl bg-accent px-4 py-2.5 text-sm font-semibold text-ink-inverse hover:bg-accent-hover hover:shadow-lg hover:shadow-blue-500/10 active:scale-[0.98] transition-all cursor-pointer self-start sm:self-auto"
        >
          <Plus className="size-4.5" />
          Add Floor
        </Link>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div className="rounded-xl border border-border bg-surface-card p-4.5 shadow-sm flex flex-col justify-between">
          <span className="text-xs font-bold text-ink-faint uppercase tracking-wider">Total Floors</span>
          <span className="text-2xl font-extrabold tracking-tight text-ink mt-2">{floors.length}</span>
        </div>
        <div className="rounded-xl border border-border bg-surface-card p-4.5 shadow-sm flex flex-col justify-between">
          <span className="text-xs font-bold text-ink-faint uppercase tracking-wider">Total Rooms</span>
          <span className="text-2xl font-extrabold tracking-tight text-ink mt-2">{property.totalRooms}</span>
        </div>
        <div className="rounded-xl border border-border bg-surface-card p-4.5 shadow-sm flex flex-col justify-between col-span-2">
          <span className="text-xs font-bold text-ink-faint uppercase tracking-wider">Building Occupancy</span>
          <div className="flex items-center gap-4 mt-2.5">
            <span className="text-2xl font-extrabold text-accent">{property.occupancyPercent}%</span>
            <div className="flex-grow h-2 bg-surface-page rounded-full overflow-hidden border border-border">
              <div className="h-full bg-accent rounded-full" style={{ width: `${property.occupancyPercent}%` }} />
            </div>
          </div>
        </div>
      </div>

      {/* Floors List Container */}
      <div className="rounded-2xl border border-border bg-surface-card shadow-sm overflow-hidden">
        {/* Table header (desktop only) */}
        <div className="hidden md:grid grid-cols-12 gap-4 px-6 py-3 bg-surface-page border-b border-border font-bold text-xs text-ink-muted uppercase tracking-wider items-center">
          <div className="col-span-3">Level</div>
          <div className="col-span-2 text-right pr-6">Rooms</div>
          <div className="col-span-5">Occupancy Status</div>
          <div className="col-span-2 text-right">Actions</div>
        </div>

        {/* Floor Rows */}
        {floors.length > 0 ? (
          <div className="divide-y divide-border">
            {floors.map((floor) => (
              <div
                key={floor.id}
                className="grid grid-cols-1 md:grid-cols-12 gap-4 items-center px-6 py-4.5 hover:bg-surface-page/40 transition-colors group"
              >
                {/* Level info */}
                <div className="col-span-1 md:col-span-3 flex items-center gap-3">
                  <div className="size-10 rounded-full bg-surface-page flex items-center justify-center font-mono text-xs font-bold text-ink border border-border shrink-0">
                    {floor.level}
                  </div>
                  <div>
                    <Link
                      href={`/properties/${property.id}/floors/${floor.id}/rooms`}
                      className="text-sm font-semibold text-ink hover:text-accent transition-colors"
                    >
                      {floor.name}
                    </Link>
                    <p className="text-xs text-ink-muted md:hidden mt-0.5">
                      {floor.roomsCount} Rooms · {floor.occupancyPercent}% Occupied
                    </p>
                  </div>
                </div>

                {/* Rooms count (desktop) */}
                <div className="hidden md:block col-span-2 font-mono text-xs font-semibold text-ink text-right pr-6">
                  {String(floor.roomsCount).padStart(2, "0")}
                </div>

                {/* Progress bar (desktop) */}
                <div className="hidden md:flex col-span-5 items-center gap-4 pr-6">
                  <div className="flex-1 h-1.5 rounded-full bg-surface-page border border-border overflow-hidden">
                    <div
                      className={`h-full rounded-full ${
                        floor.occupancyPercent === 100 ? "bg-surface-inverse" : "bg-accent"
                      }`}
                      style={{ width: `${floor.occupancyPercent}%` }}
                    />
                  </div>
                  <span className="font-mono text-xs font-semibold text-ink-muted w-10 text-right">
                    {floor.occupancyPercent}%
                  </span>
                </div>

                {/* Actions */}
                <div className="col-span-1 md:col-span-2 flex justify-end gap-2.5 pt-3.5 md:pt-0 border-t md:border-none border-border/40">
                  <button
                    aria-label="Edit Floor"
                    className="p-1.5 text-ink-muted hover:text-accent hover:bg-surface-page rounded-lg transition-colors cursor-pointer"
                  >
                    <Edit className="size-4" />
                  </button>
                  <button
                    onClick={() => handleDeleteFloor(floor.id, floor.level)}
                    aria-label="Delete Floor"
                    className="p-1.5 text-ink-muted hover:text-status-critical hover:bg-status-critical-soft rounded-lg transition-colors cursor-pointer"
                  >
                    <Trash2 className="size-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          /* Empty State */
          <div className="flex flex-col items-center justify-center text-center p-12 space-y-4 bg-surface-card">
            <div className="flex size-14 items-center justify-center rounded-full bg-surface-page text-ink-muted border border-border">
              <Building2 className="size-6 text-ink-faint animate-pulse" />
            </div>
            <div className="space-y-1 max-w-sm">
              <h3 className="text-sm font-bold text-ink">No Floors Configured</h3>
              <p className="text-xs text-ink-muted leading-relaxed">
                This building does not have any floor structures configured yet. Click Add Floor to begin expanding your capacity.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
