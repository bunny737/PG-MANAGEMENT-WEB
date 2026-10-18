"use client";

import React, { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Search, Phone, Mail, UserPlus, FilterX, Users, ArrowUpDown } from "lucide-react";
import { useTranslations } from "next-intl";
import { getInitials } from "@/lib/utils";
import { listResidents } from "@/lib/api";
import { PermissionGate } from "@/components/shared/PermissionGate";
import { PropertyFilter, useActiveProperty } from "@/components/shared/PropertyFilter";
import { SectionError, SectionSkeleton } from "@/components/shared/SectionState";
import { StatusPill, getStatusTone } from "@/components/shared/StatusPill";
import { queryKeys } from "@/lib/queryKeys";

const STATUS_TABS = ["all", "active", "notice_period", "vacated"] as const;

export function ResidentsDirectory() {
  const t = useTranslations("residents.directory");
  const tStatus = useTranslations("status");
  const { propertyId } = useActiveProperty();

  const [searchTerm, setSearchTerm] = useState("");
  const [selectedBlock, setSelectedBlock] = useState("");
  const [selectedFloor, setSelectedFloor] = useState("");
  const [selectedStatus, setSelectedStatus] = useState<(typeof STATUS_TABS)[number]>("all");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("asc");

  const filters = {
    property: propertyId ?? undefined,
    status: selectedStatus === "all" ? undefined : selectedStatus,
    search: searchTerm || undefined,
  };

  const { data: residents = [], isLoading, isError, refetch } = useQuery({
    queryKey: queryKeys.residents.list(filters),
    queryFn: () => listResidents(filters.property, filters.status, filters.search),
  });

  // Block/floor aren't server filters — narrowed client-side from whatever
  // the server already scoped by property/status/search.
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
        const digits = r.unit.replace(/\D/g, "");
        if (digits.length >= 3) {
          unique.add(digits.substring(0, digits.length - 2));
        }
      }
    });
    return Array.from(unique).sort((a, b) => Number(a) - Number(b));
  }, [residents]);

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

  const visibleResidents = useMemo(() => {
    return residents
      .filter((resident) => {
        const unitStr = resident.unit || "";
        const blockStr = resident.block || "";
        const matchesBlock = selectedBlock ? blockStr === selectedBlock : true;
        let matchesFloor = true;
        if (selectedFloor && unitStr) {
          const digits = unitStr.replace(/\D/g, "");
          matchesFloor = digits.length >= 3 && digits.substring(0, digits.length - 2) === selectedFloor;
        } else if (selectedFloor) {
          matchesFloor = false;
        }
        return matchesBlock && matchesFloor;
      })
      .sort((a, b) => {
        const nameA = `${a.first_name} ${a.last_name}`.toLowerCase();
        const nameB = `${b.first_name} ${b.last_name}`.toLowerCase();
        return sortOrder === "asc" ? nameA.localeCompare(nameB) : nameB.localeCompare(nameA);
      });
  }, [residents, selectedBlock, selectedFloor, sortOrder]);

  const hasClientFilters = selectedBlock || selectedFloor;

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
        <PermissionGate permission="manage_admissions">
          <Link
            href="/admissions/new"
            className="inline-flex items-center justify-center gap-2 rounded-xl bg-accent px-4 py-2.5 text-sm font-semibold text-ink-inverse hover:bg-accent-hover hover:shadow-lg hover:shadow-blue-500/10 active:scale-[0.98] transition-all cursor-pointer self-start sm:self-auto"
          >
            <UserPlus className="size-4.5" />
            {t("admitResident")}
          </Link>
        </PermissionGate>
      </div>

      {/* Filter and Search Panel */}
      <div className="bg-surface-card border border-border rounded-2xl p-5 shadow-sm space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-4">
          {/* Status Tabs */}
          <div className="flex flex-wrap gap-2">
            {STATUS_TABS.map((tab) => {
              const isActive = selectedStatus === tab;
              return (
                <button
                  key={tab}
                  onClick={() => setSelectedStatus(tab)}
                  className={`rounded-full px-4 py-1.5 text-xs font-semibold tracking-wide transition-all cursor-pointer ${
                    isActive
                      ? "bg-surface-inverse text-ink-inverse shadow-sm"
                      : "bg-surface-page text-ink-muted border border-border hover:bg-surface-card hover:text-ink"
                  }`}
                >
                  {tab === "all" ? t("statusAll") : tStatus(tab)}
                </button>
              );
            })}
          </div>
          <PropertyFilter />
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

            {hasClientFilters && (
              <button
                onClick={() => {
                  setSelectedBlock("");
                  setSelectedFloor("");
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

      {isLoading && <SectionSkeleton className="h-64" />}
      {isError && <SectionError onRetry={() => refetch()} message={t("errLoadFailed")} />}

      {/* Directory Data Grid List */}
      {!isLoading && !isError && (
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
          {visibleResidents.length > 0 ? (
            <div className="divide-y divide-border">
              {visibleResidents.map((resident) => {
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
                        label={tStatus(resident.status)}
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
      )}
    </div>
  );
}
