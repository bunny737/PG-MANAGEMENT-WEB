"use client";

import React, { useState, useEffect, useMemo } from "react";
import Link from "next/link";
import { Search, Phone, Mail, UserPlus, FilterX, Users, ArrowUpDown, LoaderCircle, AlertTriangle } from "lucide-react";
import { useTranslations } from "next-intl";
import { getInitials } from "@/lib/utils";
import { listResidents, type Resident, ApiError } from "@/lib/api";
import { StatusPill, getStatusTone } from "@/components/shared/StatusPill";

export function ResidentsDirectory() {
  const t = useTranslations("residents.directory");
  const tStatus = useTranslations("status");

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
        setError(err instanceof ApiError ? err.message : t("errLoadFailed"));
        setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [t]);

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
        if (selectedFloor && unitStr) {
          const digits = unitStr.replace(/\D/g, "");
          if (digits.length >= 3) {
            const floorNumber = digits.substring(0, digits.length - 2);
            matchesFloor = floorNumber === selectedFloor;
          } else {
            matchesFloor = false;
          }
        }

        // Status filter
        const matchesStatus = selectedStatus === "all" ? true : resident.status === selectedStatus;

        return matchesSearch && matchesBlock && matchesFloor && matchesStatus;
      })
      .sort((a, b) => {
        const nameA = `${a.first_name} ${a.last_name}`.toLowerCase();
        const nameB = `${b.first_name} ${b.last_name}`.toLowerCase();
        return sortOrder === "asc" ? nameA.localeCompare(nameB) : nameB.localeCompare(nameA);
      });
  }, [residents, searchTerm, selectedBlock, selectedFloor, selectedStatus, sortOrder]);

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-32 text-sm text-ink-muted">
        <LoaderCircle className="size-8 animate-spin text-accent" />
        <p className="font-semibold mt-2">{t("loading")}</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-4 max-w-md mx-auto py-16 text-center">
        <div className="flex size-14 items-center justify-center rounded-full bg-status-critical-soft text-status-critical border border-status-critical/10 mx-auto">
          <AlertTriangle className="size-6" />
        </div>
        <h3 className="text-lg font-bold text-ink">{t("errLoadFailed")}</h3>
        <p className="text-xs text-ink-muted leading-relaxed">{error}</p>
        <button
          onClick={() => window.location.reload()}
          className="px-4 py-2 bg-surface-inverse text-ink-inverse text-xs font-semibold rounded-xl hover:opacity-90 transition-opacity cursor-pointer shadow-sm"
        >
          {t("retry")}
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-ink md:text-3xl font-display-lg">{t("title")}</h1>
          <p className="mt-1 text-sm text-ink-muted">
            {t("subtitle")}
          </p>
        </div>
        <Link
          href="/admissions/new"
          className="inline-flex items-center justify-center gap-2 rounded-xl bg-accent px-4 py-2.5 text-sm font-semibold text-ink-inverse hover:bg-accent-hover hover:shadow-lg hover:shadow-blue-500/10 active:scale-[0.98] transition-all cursor-pointer self-start sm:self-auto"
        >
          <UserPlus className="size-4.5" />
          {t("admitResident")}
        </Link>
      </div>

      {/* Filter and Search Panel */}
      <div className="bg-surface-card border border-border rounded-2xl p-5 shadow-sm space-y-4">
        {/* Status Tabs */}
        <div className="flex flex-wrap gap-2 border-b border-border pb-4">
          {[
            { id: "all", label: t("statusAll") },
            { id: "active", label: t("statusActive") },
            { id: "notice", label: t("statusNotice") },
            { id: "vacated", label: t("statusVacated") },
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

        {/* Filter Controls Row */}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-12 items-center">
          {/* Text Search Input */}
          <div className="relative sm:col-span-6 md:col-span-5">
            <span className="absolute inset-y-0 left-0 flex items-center pl-3.5 text-ink-faint">
              <Search className="size-4.5" />
            </span>
            <input
              type="text"
              placeholder={t("searchPlaceholder")}
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full rounded-xl border border-border bg-surface-card py-2.5 pl-10 pr-4 text-xs text-ink outline-none transition-all focus:ring-4 focus:ring-accent/15 focus:border-accent"
            />
          </div>

          {/* Building/Block Select */}
          {blocks.length > 0 && (
            <div className="sm:col-span-3 md:col-span-3">
              <select
                value={selectedBlock}
                onChange={(e) => setSelectedBlock(e.target.value)}
                className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2.5 text-xs text-ink outline-none transition-all focus:ring-4 focus:ring-accent/15 focus:border-accent"
              >
                <option value="">{t("allBuildings")}</option>
                {blocks.map((b) => (
                  <option key={b} value={b}>
                    {b}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Floor Select */}
          {floors.length > 0 && (
            <div className="sm:col-span-3 md:col-span-2">
              <select
                value={selectedFloor}
                onChange={(e) => setSelectedFloor(e.target.value)}
                className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2.5 text-xs text-ink outline-none transition-all focus:ring-4 focus:ring-accent/15 focus:border-accent"
              >
                <option value="">{t("allFloors")}</option>
                {floors.map((fl) => (
                  <option key={fl} value={fl}>
                    {t("floorLabel", { number: fl })}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Sort order toggle & Clear Filters */}
          <div className="flex items-center gap-2 sm:col-span-12 md:col-span-2 md:justify-end">
            <button
              onClick={() => setSortOrder((prev) => (prev === "asc" ? "desc" : "asc"))}
              className="flex items-center justify-center gap-1.5 rounded-xl border border-border bg-surface-page px-3 py-2.5 text-xs font-semibold text-ink-muted hover:bg-surface-card hover:text-ink transition-colors cursor-pointer"
              title={t("sortTitle")}
            >
              <ArrowUpDown className="size-3.5" />
              <span className="uppercase text-[10px] font-bold">{sortOrder}</span>
            </button>

            {(searchTerm || selectedBlock || selectedFloor || selectedStatus !== "all") && (
              <button
                onClick={() => {
                  setSearchTerm("");
                  setSelectedBlock("");
                  setSelectedFloor("");
                  setSelectedStatus("all");
                }}
                className="p-2.5 rounded-xl border border-border bg-surface-page text-ink-muted hover:bg-surface-card hover:text-status-critical transition-colors cursor-pointer"
                title={t("clearFilters")}
              >
                <FilterX className="size-4" />
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Directory Data Grid List */}
      <div className="bg-surface-card border border-border rounded-2xl shadow-sm overflow-hidden">
        {/* Table Header (Desktop) */}
        <div className="hidden md:grid grid-cols-12 gap-4 px-6 py-3.5 bg-surface-page border-b border-border font-bold text-xs text-ink-muted uppercase tracking-wider items-center">
          <div className="col-span-4">{t("tableResident")}</div>
          <div className="col-span-2">{t("tableRoomBed")}</div>
          <div className="col-span-3">{t("tableContact")}</div>
          <div className="col-span-1 text-center">{t("tableStatus")}</div>
          <div className="col-span-2 text-right">{t("tableActions")}</div>
        </div>

        {/* Rows */}
        {filteredResidents.length > 0 ? (
          <div className="divide-y divide-border">
            {filteredResidents.map((resident) => {
              const fullName = `${resident.first_name} ${resident.last_name}`.trim();
              const initials = getInitials(fullName);
              const avatarClass = getAvatarBg(fullName);

              return (
                <div
                  key={resident.id}
                  className="grid grid-cols-1 md:grid-cols-12 gap-4 items-center px-6 py-4 hover:bg-surface-page/35 transition-colors"
                >
                  {/* Resident Info Column */}
                  <div className="col-span-1 md:col-span-4 flex items-center gap-3.5">
                    <div
                      className={`size-10 rounded-full flex items-center justify-center font-bold text-xs border shrink-0 ${avatarClass}`}
                    >
                      {initials}
                    </div>
                    <div>
                      <Link
                        href={`/residents/${resident.id}`}
                        className="text-sm font-bold text-ink hover:text-accent transition-colors"
                      >
                        {fullName}
                      </Link>
                      <p className="text-xs text-ink-muted mt-0.5 md:hidden">
                        {resident.unit ? `${resident.block ? `${resident.block} · ` : ""}${resident.unit}` : t("unassigned")}
                      </p>
                    </div>
                  </div>

                  {/* Room / Bed Slot (Desktop) */}
                  <div className="hidden md:block col-span-2 text-xs">
                    <p className="font-semibold text-ink">
                      {resident.unit || "--"}
                    </p>
                    <p className="text-[10px] text-ink-muted mt-0.5">
                      {resident.block || t("mainBuilding")}
                    </p>
                  </div>

                  {/* Contact Info (Desktop) */}
                  <div className="hidden md:block col-span-3 text-xs space-y-1">
                    <div className="flex items-center gap-1.5 text-ink">
                      <Phone className="size-3 text-ink-faint shrink-0" />
                      <span>{resident.phone}</span>
                    </div>
                    <div className="flex items-center gap-1.5 text-ink-muted truncate max-w-[200px]">
                      <Mail className="size-3 text-ink-faint shrink-0" />
                      <span className="truncate">{resident.email}</span>
                    </div>
                  </div>

                  {/* Status Badge */}
                  <div className="col-span-1 md:col-span-1 flex md:justify-center">
                    <StatusPill
                      label={tStatus(resident.status as "inquiry" | "reserved" | "active" | "notice_period" | "vacated" | "absconded" | "blacklisted" | "inactive") ?? resident.status}
                      tone={getStatusTone(resident.status)}
                    />
                  </div>

                  {/* Action Link */}
                  <div className="col-span-1 md:col-span-2 flex justify-end">
                    <Link
                      href={`/residents/${resident.id}`}
                      className="text-xs font-bold text-accent hover:text-accent-hover transition-colors inline-flex items-center gap-1"
                    >
                      {t("viewProfile")} ›
                    </Link>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          /* Empty State */
          <div className="flex flex-col items-center justify-center p-12 text-center space-y-3">
            <div className="flex size-12 items-center justify-center rounded-full bg-surface-page text-ink-muted border border-border">
              <Users className="size-6 text-ink-faint" />
            </div>
            <div className="space-y-1 max-w-sm">
              <h3 className="text-sm font-bold text-ink">{t("emptyTitle")}</h3>
              <p className="text-xs text-ink-muted leading-relaxed">
                {t("emptyDesc")}
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
