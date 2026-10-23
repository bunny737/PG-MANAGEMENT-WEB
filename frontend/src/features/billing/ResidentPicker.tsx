"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { listResidents, type Resident } from "@/lib/api";
import { queryKeys } from "@/lib/queryKeys";

interface ResidentPickerProps {
  propertyId?: string | null;
  value: string;
  onChange: (residentId: string) => void;
  placeholder: string;
  /** Billing actions only make sense for a currently billable resident. */
  statuses?: string;
}

/** A search-as-you-type resident combobox for the generate-invoice and
 * add-discount dialogs. Deliberately plain (no portal/floating-ui) — the
 * dropdown is a simple absolutely-positioned list, matching this
 * codebase's existing dialog/select conventions. */
export function ResidentPicker({
  propertyId,
  value,
  onChange,
  placeholder,
  statuses = "active,notice_period",
}: ResidentPickerProps) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);

  const { data: residents = [] } = useQuery({
    queryKey: [...queryKeys.residents.list({ property: propertyId, statuses })],
    queryFn: () => listResidents(propertyId ?? undefined, statuses),
  });

  const selected = residents.find((resident) => resident.id === value);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return residents.slice(0, 20);
    return residents
      .filter((resident) => {
        const name = `${resident.first_name} ${resident.last_name}`.toLowerCase();
        return name.includes(q) || resident.phone.includes(q);
      })
      .slice(0, 20);
  }, [residents, query]);

  function label(resident: Resident) {
    return `${resident.first_name} ${resident.last_name}`.trim() || resident.phone;
  }

  return (
    <div className="relative">
      <input
        type="text"
        value={selected ? label(selected) : query}
        onChange={(event) => {
          onChange("");
          setQuery(event.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 100)}
        placeholder={placeholder}
        className="w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
      />
      {open && filtered.length > 0 && (
        <div className="absolute z-10 mt-1 max-h-56 w-full overflow-y-auto rounded-xl border border-border bg-surface-card shadow-lg">
          {filtered.map((resident) => (
            <button
              key={resident.id}
              type="button"
              onClick={() => {
                onChange(resident.id);
                setQuery("");
                setOpen(false);
              }}
              className="flex w-full flex-col items-start px-3 py-2 text-left text-sm transition-colors hover:bg-surface-page cursor-pointer"
            >
              <span className="font-medium text-ink">{label(resident)}</span>
              <span className="text-xs text-ink-muted">{resident.phone}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
