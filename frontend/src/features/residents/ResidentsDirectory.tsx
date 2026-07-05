"use client";

import React, { useState, useEffect, useMemo } from "react";
import Link from "next/link";
import { Search, Phone, Mail, UserPlus, FilterX, Users, ArrowUpDown, LoaderCircle, AlertTriangle } from "lucide-react";
import { getInitials } from "@/lib/utils";
import { listResidents, type Resident, ApiError } from "@/lib/api";

export function ResidentsDirectory() {
  const [residents, setResidents] = useState<Resident[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");

  // Filter States
  const [searchTerm, setSearchTerm] = useState("");
  const [selectedBlock, setSelectedBlock] = useState("");
  const [selectedFloor, setSelectedFloor] = useState("");
  const [selectedStatus, setSelectedStatus] = useState("all");

  // Sorting
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("asc");

  useEffect(() => {
    let cancelled = false;

    listResidents()
      .then((data) => {
        if (cancelled) return;
        setResidents(data);
        setIsLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        console.error(err);
        setError(err instanceof ApiError ? err.message : "Failed to load residents list. Please try again.");
        setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  // Dynamically collect unique blocks/buildings and floors from the loaded residents list
  const blocks = useMemo(() => {
    const unique = new Set<string>();
    residents.forEach((r) => {
      if (r.block) unique.add(r.block);
    });
    return Array.from(unique).sort();
  }, [residents]);

  const floors = useMemo(() => {
    const unique = new Set<string>();
    residents.forEach((r) => {
      if (r.unit) {
        // e.g. "Room 401" -> extract digits (e.g. 401) -> extract floor (e.g. 4)
        const digits = r.unit.replace(/\D/g, "");
        if (digits.length >= 3) {
          unique.add(digits.substring(0, digits.length - 2));
        }
      }
    });
    return Array.from(unique).sort((a, b) => Number(a) - Number(b));
  }, [residents]);

  // Avatar Background Color Helper
  const getAvatarBg = (name: string) => {
    const hash = name.split("").reduce((acc, char) => acc + char.charCodeAt(0), 0);
    const colors = [
      "bg-blue-100 text-blue-800 border-blue-200",
      "bg-indigo-100 text-indigo-800 border-indigo-200",
      "bg-purple-100 text-purple-800 border-purple-200",
      "bg-emerald-100 text-emerald-800 border-emerald-200",
      "bg-violet-100 text-violet-800 border-violet-200",
      "bg-amber-100 text-amber-800 border-amber-200",
    ];
    return colors[hash % colors.length];
  };

  // Filtered and Sorted Residents
  const filteredResidents = useMemo(() => {
    return residents
      .filter((resident) => {
        const fullName = `${resident.first_name} ${resident.last_name}`.trim();
        const unitStr = resident.unit || "";
        const blockStr = resident.block || "";

        // Search filter (name, unit, phone, email)
        const query = searchTerm.toLowerCase();
        const matchesSearch =
          fullName.toLowerCase().includes(query) ||
          unitStr.toLowerCase().includes(query) ||
          resident.phone.includes(query) ||
          resident.email.toLowerCase().includes(query);

        // Block filter
        const matchesBlock = selectedBlock ? blockStr === selectedBlock : true;

        // Floor filter (extract room digits and check prefix matching floor)
        let matchesFloor = true;
        if (selectedFloor) {
          const roomDigits = unitStr.replace(/^\D+/g, ""); // e.g. "401"
          matchesFloor = roomDigits.startsWith(selectedFloor);
        }

        // Status filter
        let matchesStatus = true;
        if (selectedStatus !== "all") {
          if (selectedStatus === "inactive") {
            matchesStatus = ["vacated", "absconded", "blacklisted", "inactive"].includes(resident.status);
          } else {
            matchesStatus = resident.status === selectedStatus;
          }
        }

        return matchesSearch && matchesBlock && matchesFloor && matchesStatus;
      })
      .sort((a, b) => {
        const nameA = `${a.first_name} ${a.last_name}`.trim();
        const nameB = `${b.first_name} ${b.last_name}`.trim();
        if (sortOrder === "asc") {
          return nameA.localeCompare(nameB);
        } else {
          return nameB.localeCompare(nameA);
        }
      });
  }, [residents, searchTerm, selectedBlock, selectedFloor, selectedStatus, sortOrder]);

  const handleResetFilters = () => {
    setSearchTerm("");
    setSelectedBlock("");
    setSelectedFloor("");
    setSelectedStatus("all");
  };

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-32 text-sm text-ink-muted">
        <LoaderCircle className="size-8 animate-spin text-accent" />
        <p className="font-semibold mt-2">Loading resident directory...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-4 max-w-md mx-auto py-16 text-center">
        <div className="flex size-14 items-center justify-center rounded-full bg-status-critical-soft text-status-critical border border-status-critical/10 mx-auto">
          <AlertTriangle className="size-6" />
        </div>
        <h3 className="text-lg font-bold text-ink">Failed to Load Directory</h3>
        <p className="text-xs text-ink-muted leading-relaxed">{error}</p>
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
      {/* Directory Title / Header */}
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-ink md:text-3xl">Resident Directory</h1>
          <p className="mt-1 text-sm text-ink-muted">
            Manage, filter, and contact all occupants in active leases.
          </p>
        </div>
        <Link
          href="/admissions"
          className="inline-flex items-center justify-center gap-2 rounded-xl bg-accent px-4 py-2.5 text-sm font-semibold text-ink-inverse hover:bg-accent-hover hover:shadow-lg hover:shadow-blue-500/10 active:scale-[0.98] transition-all cursor-pointer self-start sm:self-auto"
        >
          <UserPlus className="size-4.5" />
          Add Resident
        </Link>
      </div>

      {/* Search and Filters panel */}
      <div className="rounded-2xl border border-border bg-surface-card p-5 shadow-sm space-y-4">
        {/* Status Pill Filters */}
        <div className="flex flex-wrap gap-2 border-b border-border pb-4">
          {[
            { id: "all", label: "All Tenants" },
            { id: "active", label: "Active" },
            { id: "notice_period", label: "Notice Period" },
            { id: "reserved", label: "Reserved" },
            { id: "inquiry", label: "Inquiry" },
            { id: "inactive", label: "Inactive" },
          ].map((tab) => {
            const isActive = selectedStatus === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setSelectedStatus(tab.id)}
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

        {/* Text Search & Dropdowns selectors */}
        <div className="flex flex-col gap-4 md:flex-row">
          {/* Search box */}
          <div className="relative flex-1">
            <span className="absolute inset-y-0 left-0 flex items-center pl-3.5 text-ink-faint">
              <Search className="size-4.5" />
            </span>
            <input
              type="text"
              placeholder="Search by name, room, phone, or email..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full rounded-xl border border-border bg-surface-card py-2.5 pl-10 pr-4 text-sm text-ink outline-none transition-all focus:ring-4 focus:ring-accent/15 focus:border-accent"
            />
          </div>

          {/* Block dropdown */}
          <div className="w-full md:w-44">
            <select
              value={selectedBlock}
              onChange={(e) => setSelectedBlock(e.target.value)}
              className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2.5 text-sm text-ink-muted outline-none transition-all focus:ring-4 focus:ring-accent/15 focus:border-accent"
            >
              <option value="">All Blocks</option>
              {blocks.map((block) => (
                <option key={block} value={block}>
                  Block {block}
                </option>
              ))}
            </select>
          </div>

          {/* Floor dropdown */}
          <div className="w-full md:w-44">
            <select
              value={selectedFloor}
              onChange={(e) => setSelectedFloor(e.target.value)}
              className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2.5 text-sm text-ink-muted outline-none transition-all focus:ring-4 focus:ring-accent/15 focus:border-accent"
            >
              <option value="">All Floors</option>
              {floors.map((floor) => (
                <option key={floor} value={floor}>
                  Floor {floor}
                </option>
              ))}
            </select>
          </div>

          {/* Reset Filters Icon Button */}
          {(searchTerm || selectedBlock || selectedFloor || selectedStatus !== "all") && (
            <button
              onClick={handleResetFilters}
              className="flex items-center justify-center gap-2 rounded-xl border border-border bg-surface-page p-2.5 text-sm font-medium text-ink-muted hover:bg-surface-card hover:text-ink transition-colors cursor-pointer"
              title="Clear all filters"
            >
              <FilterX className="size-5" />
              <span className="md:hidden">Reset Filters</span>
            </button>
          )}
        </div>
      </div>

      {/* Directory Table / Grid */}
      {filteredResidents.length > 0 ? (
        <div className="rounded-2xl border border-border bg-surface-card shadow-sm overflow-hidden">
          {/* Desktop Table Layout (md+) */}
          <div className="hidden md:block overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="bg-surface-page border-b border-border">
                  <th className="px-6 py-4.5 text-xs font-semibold uppercase tracking-wider text-ink-muted">
                    <button
                      onClick={() => setSortOrder(sortOrder === "asc" ? "desc" : "asc")}
                      className="flex items-center gap-1.5 hover:text-ink transition-colors cursor-pointer font-semibold uppercase tracking-wider text-xs"
                    >
                      Resident
                      <ArrowUpDown className="size-3.5 text-ink-faint" />
                    </button>
                  </th>
                  <th className="px-6 py-4.5 text-xs font-semibold uppercase tracking-wider text-ink-muted">
                    Unit
                  </th>
                  <th className="px-6 py-4.5 text-xs font-semibold uppercase tracking-wider text-ink-muted">
                    Status
                  </th>
                  <th className="px-6 py-4.5 text-xs font-semibold uppercase tracking-wider text-ink-muted">
                    Move In
                  </th>
                  <th className="px-6 py-4.5 text-xs font-semibold uppercase tracking-wider text-ink-muted text-right">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {filteredResidents.map((resident) => {
                  const fullName = `${resident.first_name} ${resident.last_name}`.trim();
                  return (
                    <tr
                      key={resident.id}
                      className="hover:bg-surface-page/40 transition-colors"
                    >
                      {/* Resident Info column */}
                      <td className="px-6 py-4">
                        <Link
                          href={`/residents/${resident.id}`}
                          className="flex items-center gap-3 group hover:opacity-90 transition-opacity"
                        >
                          <span
                            className={`flex size-10 shrink-0 items-center justify-center rounded-full border text-sm font-bold ${getAvatarBg(
                              fullName
                            )}`}
                          >
                            {getInitials(fullName)}
                          </span>
                          <div className="flex flex-col">
                            <span className="text-sm font-semibold text-ink group-hover:text-accent transition-colors">
                              {fullName}
                            </span>
                            <span className="text-xs text-ink-muted">{resident.email}</span>
                          </div>
                        </Link>
                      </td>

                      {/* Unit ID Column */}
                      <td className="px-6 py-4">
                        <span className="font-mono text-xs font-semibold text-ink bg-surface-page border border-border px-2.5 py-1 rounded-md">
                          {resident.unit || "Not Allocated"}
                        </span>
                      </td>

                      {/* Status Badge column */}
                      <td className="px-6 py-4">
                        {resident.status === "active" && (
                          <span className="inline-flex items-center rounded-full bg-blue-50 px-2.5 py-0.5 text-xs font-semibold text-blue-700 border border-blue-100">
                            Active
                          </span>
                        )}
                        {resident.status === "notice_period" && (
                          <span className="inline-flex items-center rounded-full bg-red-50 px-2.5 py-0.5 text-xs font-semibold text-red-700 border border-red-100">
                            Notice Period
                          </span>
                        )}
                        {resident.status === "reserved" && (
                          <span className="inline-flex items-center rounded-full bg-amber-50 px-2.5 py-0.5 text-xs font-semibold text-amber-700 border border-amber-100">
                            Reserved
                          </span>
                        )}
                        {resident.status === "inquiry" && (
                          <span className="inline-flex items-center rounded-full bg-indigo-50 px-2.5 py-0.5 text-xs font-semibold text-indigo-700 border border-indigo-100">
                            Inquiry
                          </span>
                        )}
                        {resident.status === "inactive" && (
                          <span className="inline-flex items-center rounded-full bg-slate-50 px-2.5 py-0.5 text-xs font-semibold text-slate-500 border border-slate-200">
                            Inactive
                          </span>
                        )}
                      </td>

                      {/* Move In Date Column */}
                      <td className="px-6 py-4 text-sm text-ink-muted">
                        {resident.move_in_date || "N/A"}
                      </td>

                      {/* Action buttons column */}
                      <td className="px-6 py-4 text-right">
                        <div className="inline-flex items-center gap-2">
                          <a
                            href={`tel:${resident.phone}`}
                            className="flex size-9 items-center justify-center rounded-full border border-border text-ink-muted hover:bg-surface-page hover:text-accent hover:border-accent/35 transition-all cursor-pointer"
                            title={`Call ${fullName} (${resident.phone})`}
                          >
                            <Phone className="size-4" />
                          </a>
                          <a
                            href={`mailto:${resident.email}`}
                            className="flex size-9 items-center justify-center rounded-full border border-border text-ink-muted hover:bg-surface-page hover:text-accent hover:border-accent/35 transition-all cursor-pointer"
                            title={`Email ${fullName} (${resident.email})`}
                          >
                            <Mail className="size-4" />
                          </a>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Mobile Grid/List Layout (< md) */}
          <div className="block md:hidden divide-y divide-border">
            {filteredResidents.map((resident) => {
              const fullName = `${resident.first_name} ${resident.last_name}`.trim();
              return (
                <div key={resident.id} className="p-4 space-y-3.5 hover:bg-surface-page/30 transition-colors">
                  {/* Header card info */}
                  <div className="flex items-start justify-between">
                    <Link
                      href={`/residents/${resident.id}`}
                      className="flex items-center gap-3 group hover:opacity-90 transition-opacity"
                    >
                      <span
                        className={`flex size-10 shrink-0 items-center justify-center rounded-full border text-sm font-bold ${getAvatarBg(
                          fullName
                        )}`}
                      >
                        {getInitials(fullName)}
                      </span>
                      <div>
                        <h4 className="text-sm font-bold text-ink group-hover:text-accent transition-colors">
                          {fullName}
                        </h4>
                        <p className="text-xs text-ink-muted">Room {resident.unit || "N/A"} · Move-in {resident.move_in_date || "N/A"}</p>
                      </div>
                    </Link>
                    
                    {/* Status Badge */}
                    <div>
                      {resident.status === "active" && (
                        <span className="inline-flex items-center rounded-full bg-blue-50 px-2.5 py-0.5 text-xs font-semibold text-blue-700 border border-blue-100">
                          Active
                        </span>
                      )}
                      {resident.status === "notice_period" && (
                        <span className="inline-flex items-center rounded-full bg-red-50 px-2.5 py-0.5 text-xs font-semibold text-red-700 border border-red-100">
                          Notice
                        </span>
                      )}
                      {resident.status === "reserved" && (
                        <span className="inline-flex items-center rounded-full bg-amber-50 px-2.5 py-0.5 text-xs font-semibold text-amber-700 border border-amber-100">
                          Reserved
                        </span>
                      )}
                      {resident.status === "inquiry" && (
                        <span className="inline-flex items-center rounded-full bg-indigo-50 px-2.5 py-0.5 text-xs font-semibold text-indigo-700 border border-indigo-100">
                          Inquiry
                        </span>
                      )}
                      {resident.status === "inactive" && (
                        <span className="inline-flex items-center rounded-full bg-slate-50 px-2.5 py-0.5 text-xs font-semibold text-slate-500 border border-slate-200">
                          Inactive
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Subinfo & Contact buttons */}
                  <div className="flex items-center justify-between border-t border-border/40 pt-3">
                    <span className="text-xs text-ink-faint font-mono">{resident.email}</span>
                    <div className="flex gap-2">
                      <a
                        href={`tel:${resident.phone}`}
                        className="flex size-9 items-center justify-center rounded-full border border-border bg-surface-card text-ink-muted hover:bg-surface-page hover:text-accent transition-colors"
                        title="Call"
                      >
                        <Phone className="size-4" />
                      </a>
                      <a
                        href={`mailto:${resident.email}`}
                        className="flex size-9 items-center justify-center rounded-full border border-border bg-surface-card text-ink-muted hover:bg-surface-page hover:text-accent transition-colors"
                        title="Email"
                      >
                        <Mail className="size-4" />
                      </a>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ) : (
        /* Empty State */
        <div className="flex flex-col items-center justify-center text-center rounded-2xl border border-border bg-surface-card p-12 shadow-sm space-y-4">
          <div className="flex size-14 items-center justify-center rounded-full bg-surface-page text-ink-muted border border-border">
            <Users className="size-6 text-ink-faint animate-pulse" />
          </div>
          <div className="space-y-1 max-w-sm">
            <h3 className="text-base font-bold text-ink">No residents found</h3>
            <p className="text-xs text-ink-muted leading-relaxed">
              We couldn&apos;t find any residents matching your active filters. Try refining your search string or resetting filters.
            </p>
          </div>
          <button
            onClick={handleResetFilters}
            className="rounded-xl border border-border bg-surface-page px-4 py-2 text-xs font-semibold text-ink hover:bg-surface-card transition-colors cursor-pointer"
          >
            Clear Filters
          </button>
        </div>
      )}
    </div>
  );
}
