"use client";

import React, { useEffect, useState, useMemo } from "react";
import Link from "next/link";
import { ChevronRight, Plus, Search, FilterX, User, Wrench, ShieldAlert, LoaderCircle, AlertTriangle } from "lucide-react";
import { getProperty, getFloor, listRooms, type Property, type Room, ApiError } from "@/lib/api";

export function RoomList({ propertyId, floorId }: { propertyId: string; floorId: string }) {
  const [property, setProperty] = useState<Property | null>(null);
  const [floorName, setFloorName] = useState("");
  const [rooms, setRooms] = useState<Room[] | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");

  const [searchTerm, setSearchTerm] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");

  // Track propertyId / floorId changes to reset loading state (React render-time adjustment pattern)
  const [prevIds, setPrevIds] = useState({ propertyId, floorId });
  if (propertyId !== prevIds.propertyId || floorId !== prevIds.floorId) {
    setPrevIds({ propertyId, floorId });
    setIsLoading(true);
    setError("");
  }

  useEffect(() => {
    let cancelled = false;

    Promise.all([getProperty(propertyId), getFloor(floorId), listRooms(floorId)])
      .then(([propData, floorData, roomsData]) => {
        if (cancelled) return;
        setProperty(propData);
        setFloorName(floorData.name);
        setRooms(roomsData);
        setIsLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        console.error(err);
        setError(err instanceof ApiError ? err.message : "Failed to load room details. Please try again.");
        setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [propertyId, floorId]);

  const filteredRooms = useMemo(() => {
    if (!rooms) return [];
    return rooms.filter((room) => {
      // Search filter (room_number)
      const matchesSearch = room.room_number.toLowerCase().includes(searchTerm.toLowerCase());

      // Status filter
      let matchesStatus = true;
      if (statusFilter === "available") {
        matchesStatus = room.beds?.some((b) => b.status === "available") || room.status === "available";
      } else if (statusFilter === "occupied") {
        matchesStatus = room.current_occupancy === room.bed_capacity || room.status === "occupied";
      } else if (statusFilter === "maintenance") {
        matchesStatus = room.beds?.some((b) => b.status === "maintenance") || room.status === "maintenance";
      }

      return matchesSearch && matchesStatus;
    });
  }, [rooms, searchTerm, statusFilter]);

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-32 text-sm text-ink-muted">
        <LoaderCircle className="size-8 animate-spin text-accent" />
        <p className="font-semibold mt-2">Loading rooms list...</p>
      </div>
    );
  }

  if (error || !property || !rooms) {
    return (
      <div className="space-y-4 max-w-md mx-auto py-16 text-center">
        <div className="flex size-14 items-center justify-center rounded-full bg-status-critical-soft text-status-critical border border-status-critical/10 mx-auto">
          <AlertTriangle className="size-6" />
        </div>
        <h3 className="text-lg font-bold text-ink">Failed to Load Rooms</h3>
        <p className="text-xs text-ink-muted leading-relaxed">
          {error || "Could not retrieve rooms data."}
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
      {/* Header */}
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
                <span className="text-ink font-semibold">{floorName}</span>
              </li>
            </ol>
          </nav>
          <h1 className="text-2xl font-bold tracking-tight text-ink md:text-3xl">Rooms Portfolio</h1>
        </div>

        <Link
          href={`/properties/${property.id}/floors/${floorId}/rooms/add`}
          className="inline-flex items-center justify-center gap-2 rounded-xl bg-accent px-4 py-2.5 text-sm font-semibold text-ink-inverse hover:bg-accent-hover hover:shadow-lg hover:shadow-blue-500/10 active:scale-[0.98] transition-all cursor-pointer self-start sm:self-auto"
        >
          <Plus className="size-4.5" />
          Add Room
        </Link>
      </div>

      {/* Filter panel */}
      <div className="rounded-2xl border border-border bg-surface-card p-5 shadow-sm space-y-4">
        {/* Status Pill Filters */}
        <div className="flex flex-wrap gap-2 border-b border-border pb-4">
          {[
            { id: "all", label: "All Units" },
            { id: "available", label: "Available Beds" },
            { id: "occupied", label: "Fully Occupied" },
            { id: "maintenance", label: "Under Maintenance" },
          ].map((tab) => {
            const isActive = statusFilter === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setStatusFilter(tab.id)}
                className={`rounded-full px-4 py-1.5 text-xs font-semibold tracking-wide transition-all cursor-pointer ${
                  isActive
                    ? "bg-surface-inverse text-ink-inverse shadow-sm"
                    : "bg-surface-page text-ink-muted border border-border hover:bg-surface-card hover:text-ink"
                }`}
              >
                {tab.label}
              </button>
            );
          })}
        </div>

        {/* Text Search */}
        <div className="flex flex-col gap-4 sm:flex-row">
          <div className="relative flex-1 max-w-md">
            <span className="absolute inset-y-0 left-0 flex items-center pl-3.5 text-ink-faint">
              <Search className="size-4.5" />
            </span>
            <input
              type="text"
              placeholder="Search by room name..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full rounded-xl border border-border bg-surface-card py-2.5 pl-10 pr-4 text-sm text-ink outline-none transition-all focus:ring-4 focus:ring-accent/15 focus:border-accent"
            />
          </div>

          {(searchTerm || statusFilter !== "all") && (
            <button
              onClick={() => {
                setSearchTerm("");
                setStatusFilter("all");
              }}
              className="flex items-center justify-center gap-2 rounded-xl border border-border bg-surface-page px-4 py-2.5 text-sm font-medium text-ink-muted hover:bg-surface-card hover:text-ink transition-colors cursor-pointer"
            >
              <FilterX className="size-4.5" /> Clear Filters
            </button>
          )}
        </div>
      </div>

      {/* Grid List */}
      {filteredRooms.length > 0 ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {filteredRooms.map((room) => {
            const isFull = room.current_occupancy === room.bed_capacity;
            const hasMaintenance = room.beds?.some((b) => b.status === "maintenance") || room.status === "maintenance";
            
            // Find target bed for link
            const targetBed = room.beds?.find((b) => b.status === "maintenance") || room.beds?.[0];
            const targetBedId = targetBed?.id;
            
            const viewDetailsUrl = targetBedId 
              ? `/properties/${property.id}/floors/${floorId}/rooms/${room.id}/beds/${targetBedId}`
              : `/properties/${property.id}/floors/${floorId}/rooms/${room.id}`;

            const sharingTypeLabel = room.sharing_type === 1 
              ? "Single" 
              : room.sharing_type === 2 
              ? "Double" 
              : room.sharing_type === 3 
              ? "Triple" 
              : room.sharing_type === 4 
              ? "Four" 
              : room.sharing_type === 5
              ? "Five"
              : room.sharing_type === 6
              ? "Six"
              : room.sharing_type === 7
              ? "Seven"
              : room.sharing_type === 8
              ? "Eight"
              : `${room.sharing_type}-sharing`;

            return (
              <div
                key={room.id}
                className="bg-surface-card border border-border rounded-2xl p-5 flex flex-col justify-between hover:shadow-md transition-shadow relative overflow-hidden group"
              >
                <div className="flex justify-between items-start mb-4">
                  <div>
                    <Link
                      href={viewDetailsUrl}
                      className="text-lg font-bold text-ink hover:text-accent transition-colors tracking-tight"
                    >
                      {room.room_number}
                    </Link>
                    <p className="text-xs text-ink-muted mt-0.5 flex items-center gap-1">
                      <User className="size-3.5" />
                      {sharingTypeLabel} sharing
                    </p>
                  </div>

                  <span
                    className={`p-1.5 rounded-lg text-xs font-semibold uppercase ${
                      room.category === "ac" 
                        ? "bg-blue-50 text-blue-600 border border-blue-100" 
                        : "bg-amber-50 text-amber-600 border border-amber-100"
                    }`}
                    title={room.category === "ac" ? "AC Room" : "Non-AC Room"}
                  >
                    {room.category}
                  </span>
                </div>

                <div className="space-y-1.5 mt-2">
                  <div className="flex justify-between items-baseline text-xs">
                    <span className="text-ink-muted">Beds Occupancy</span>
                    <span className="font-semibold text-ink">
                      {room.current_occupancy}/{room.bed_capacity} occupied
                    </span>
                  </div>
                  {/* Occupancy bar */}
                  <div className="h-1.5 w-full bg-surface-page rounded-full overflow-hidden border border-border">
                    <div
                      className={`h-full rounded-full ${
                        hasMaintenance ? "bg-status-critical" : isFull ? "bg-slate-700" : "bg-accent"
                      }`}
                      style={{ width: `${(room.current_occupancy / room.bed_capacity) * 100}%` }}
                    />
                  </div>
                </div>

                {/* Card footer details */}
                <div className="mt-5 pt-3 flex justify-between items-center border-t border-border/60">
                  {hasMaintenance ? (
                    <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-status-critical-soft text-status-critical font-bold text-[10px] uppercase tracking-wider border border-status-critical/10">
                      <Wrench className="size-3 shrink-0" />
                      Maintenance
                    </span>
                  ) : isFull ? (
                    <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-slate-100 text-slate-700 font-bold text-[10px] uppercase tracking-wider border border-slate-200">
                      Occupied
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-accent-soft text-accent font-bold text-[10px] uppercase tracking-wider border border-accent/10">
                      Available
                    </span>
                  )}

                  <Link
                    href={viewDetailsUrl}
                    className="text-xs font-bold text-ink-muted hover:text-accent transition-colors"
                  >
                    View Details ›
                  </Link>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        /* Empty State */
        <div className="flex flex-col items-center justify-center text-center p-12 space-y-4 bg-surface-card border border-border rounded-2xl">
          <div className="flex size-14 items-center justify-center rounded-full bg-surface-page text-ink-muted border border-border">
            <ShieldAlert className="size-6 text-ink-faint animate-pulse" />
          </div>
          <div className="space-y-1 max-w-sm">
            <h3 className="text-sm font-bold text-ink">No Rooms Found</h3>
            <p className="text-xs text-ink-muted leading-relaxed">
              We couldn&apos;t find any rooms matching your active filters. Try clearing your search term.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
