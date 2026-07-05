"use client";

import React, { useState, useMemo } from "react";
import Link from "next/link";
import { ChevronRight, Plus, Search, FilterX, User, Wrench, ShieldAlert } from "lucide-react";
import { mockProperties } from "./mock-properties";

export function RoomList({ propertyId, floorId }: { propertyId: string; floorId: string }) {
  const property = mockProperties.find((p) => p.id === propertyId) || mockProperties[0];
  const floor = property.floors.find((f) => f.id === floorId) || property.floors[0] || { id: floorId, level: floorId, name: `Floor ${floorId}`, rooms: [] };

  // If the floor has no rooms, let's load some default mock rooms based on the design
  const defaultRooms = useMemo(() => {
    if (floor.rooms && floor.rooms.length > 0) return floor.rooms;

    // Load mock rooms matching the HTML mockup design
    return [
      {
        id: "101",
        name: "101-A",
        sharingType: "single" as const,
        category: "ac" as const,
        rent: "$850.00",
        occupiedBeds: 0,
        totalBeds: 1,
        amenities: ["Wi-Fi", "Cleaning", "Laundry"],
        beds: [
          {
            id: "A",
            name: "Bed A",
            status: "available" as const,
            rackRate: "$850.00",
            deposit: "$400.00",
            history: []
          }
        ]
      },
      {
        id: "204",
        name: "204-B",
        sharingType: "double" as const,
        category: "non-ac" as const,
        rent: "$650.00",
        occupiedBeds: 1,
        totalBeds: 2,
        amenities: ["Wi-Fi", "Cleaning"],
        beds: [
          {
            id: "A",
            name: "Bed A",
            status: "occupied" as const,
            currentOccupant: "Rohan Sharma",
            rackRate: "$650.00",
            deposit: "$300.00",
            history: []
          },
          {
            id: "B",
            name: "Bed B",
            status: "available" as const,
            rackRate: "$650.00",
            deposit: "$300.00",
            history: []
          }
        ]
      },
      {
        id: "310",
        name: "310-C",
        sharingType: "triple" as const,
        category: "ac" as const,
        rent: "$600.00",
        occupiedBeds: 3,
        totalBeds: 3,
        amenities: ["Wi-Fi", "Cleaning", "Laundry"],
        beds: [
          { id: "A", name: "Bed A", status: "occupied" as const, currentOccupant: "Priya Patel", rackRate: "$600.00", deposit: "$300.00", history: [] },
          { id: "B", name: "Bed B", status: "occupied" as const, currentOccupant: "Nikhil K.", rackRate: "$600.00", deposit: "$300.00", history: [] },
          { id: "C", name: "Bed C", status: "occupied" as const, currentOccupant: "Karan S.", rackRate: "$600.00", deposit: "$300.00", history: [] }
        ]
      },
      {
        id: "402",
        name: "402-B",
        sharingType: "double" as const,
        category: "ac" as const,
        rent: "$850.00",
        occupiedBeds: 1,
        totalBeds: 2,
        amenities: ["Wi-Fi", "Cleaning", "Laundry"],
        beds: [
          {
            id: "A",
            name: "Bed A",
            status: "occupied" as const,
            currentOccupant: "Alex Smith",
            rackRate: "$850.00",
            deposit: "$400.00",
            history: []
          },
          {
            id: "B",
            name: "Bed B",
            status: "maintenance" as const,
            rackRate: "$850.00",
            deposit: "$400.00",
            maintenanceIssue: {
              id: "WO-4921",
              issue: "Reported broken bed frame slat. Scheduled for repair by internal team on 10/24/2023.",
              date: "10/21/2023",
              reporter: "Staff (J. Doe)"
            },
            history: []
          }
        ]
      }
    ];
  }, [floor.rooms]);

  const [searchTerm, setSearchTerm] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");

  const filteredRooms = useMemo(() => {
    return defaultRooms.filter((room) => {
      // Search filter (room name)
      const matchesSearch = room.name.toLowerCase().includes(searchTerm.toLowerCase());

      // Status filter
      let matchesStatus = true;
      if (statusFilter === "available") {
        matchesStatus = room.beds.some((b) => b.status === "available");
      } else if (statusFilter === "occupied") {
        matchesStatus = room.occupiedBeds === room.totalBeds;
      } else if (statusFilter === "maintenance") {
        matchesStatus = room.beds.some((b) => b.status === "maintenance");
      }

      return matchesSearch && matchesStatus;
    });
  }, [defaultRooms, searchTerm, statusFilter]);

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
                <span className="text-ink font-semibold">{floor.name}</span>
              </li>
            </ol>
          </nav>
          <h1 className="text-2xl font-bold tracking-tight text-ink md:text-3xl">Rooms Portfolio</h1>
        </div>

        <Link
          href={`/properties/${property.id}/floors/${floor.id}/rooms/add`}
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
            const isFull = room.occupiedBeds === room.totalBeds;
            const hasMaintenance = room.beds.some((b) => b.status === "maintenance");
            // Let's find the first bed ID that matches status or go to Bed B if it is in maintenance
            const targetBed = room.beds.find((b) => b.status === "maintenance") || room.beds[0] || { id: "A" };

            return (
              <div
                key={room.id}
                className="bg-surface-card border border-border rounded-2xl p-5 flex flex-col justify-between hover:shadow-md transition-shadow relative overflow-hidden group"
              >
                <div className="flex justify-between items-start mb-4">
                  <div>
                    <Link
                      href={`/properties/${property.id}/floors/${floor.id}/rooms/${room.id}/beds/${targetBed.id}`}
                      className="text-lg font-bold text-ink hover:text-accent transition-colors tracking-tight"
                    >
                      {room.name}
                    </Link>
                    <p className="text-xs text-ink-muted mt-0.5 flex items-center gap-1">
                      <User className="size-3.5" />
                      {room.sharingType.charAt(0).toUpperCase() + room.sharingType.slice(1)} sharing
                    </p>
                  </div>

                  <span
                    className={`p-1.5 rounded-lg text-xs font-semibold ${
                      room.category === "ac" 
                        ? "bg-blue-50 text-blue-600 border border-blue-100" 
                        : "bg-amber-50 text-amber-600 border border-amber-100"
                    }`}
                    title={room.category === "ac" ? "AC Room" : "Non-AC Room"}
                  >
                    {room.category.toUpperCase()}
                  </span>
                </div>

                <div className="space-y-1.5 mt-2">
                  <div className="flex justify-between items-baseline text-xs">
                    <span className="text-ink-muted">Beds Occupancy</span>
                    <span className="font-semibold text-ink">
                      {room.occupiedBeds}/{room.totalBeds} occupied
                    </span>
                  </div>
                  {/* Occupancy bar */}
                  <div className="h-1.5 w-full bg-surface-page rounded-full overflow-hidden border border-border">
                    <div
                      className={`h-full rounded-full ${
                        hasMaintenance ? "bg-status-critical" : isFull ? "bg-slate-700" : "bg-accent"
                      }`}
                      style={{ width: `${(room.occupiedBeds / room.totalBeds) * 100}%` }}
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
                    href={`/properties/${property.id}/floors/${floor.id}/rooms/${room.id}/beds/${targetBed.id}`}
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
