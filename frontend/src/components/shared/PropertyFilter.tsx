"use client";

import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { listProperties } from "@/lib/api";
import { useActivePropertyStore } from "@/lib/activePropertyStore";
import { queryKeys } from "@/lib/queryKeys";
import { useSession } from "@/lib/session";
import { cn } from "@/lib/utils";

/**
 * The active-property selection, validated against the account's current
 * `/properties/` list (UX roadmap "active-property scoping"). Falls back
 * to "All" and reports `accessRevoked: true` when the saved id is no
 * longer in that list — `PropertyFilter` below shows the notice; a caller
 * that only needs the id/setter can ignore it. (The property that was
 * revoked has, by definition, dropped out of `properties`, so there is no
 * name left to show — only that the selection reset.)
 */
export function useActiveProperty() {
  const { user, ready } = useSession();
  const store = useActivePropertyStore();

  useEffect(() => {
    if (ready && user) store.hydrate(user.tenant_id ?? "", user.id);
    // store.hydrate is stable (Zustand action); only re-hydrate when the account changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, user?.tenant_id, user?.id]);

  const hydrated = ready && !!user && store.scope?.userId === user.id;

  const { data: properties = [], isSuccess: listLoaded } = useQuery({
    queryKey: queryKeys.properties.list,
    queryFn: listProperties,
    enabled: hydrated,
    staleTime: 60_000,
  });

  const savedId = store.propertyId;
  // Only judge "revoked" once the properties list has actually loaded for
  // this account — otherwise the moment before the query resolves would
  // look like every saved selection was revoked.
  const stillAssigned = savedId === null || !listLoaded || properties.some((property) => property.id === savedId);
  const accessRevoked = listLoaded && savedId !== null && !stillAssigned;
  const propertyId = stillAssigned ? savedId : null;

  return {
    propertyId,
    properties,
    accessRevoked,
    setPropertyId: store.setPropertyId,
  };
}

interface PropertyFilterProps {
  className?: string;
}

/** The property-scope dropdown shown on Dashboard/Billing/Residents/Reports
 * (UX roadmap "active-property scoping"). Shows a notice when the saved
 * selection was revoked and the view fell back to "All". */
export function PropertyFilter({ className }: PropertyFilterProps) {
  const t = useTranslations("common");
  const { propertyId, properties, accessRevoked, setPropertyId } = useActiveProperty();

  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <select
        value={propertyId ?? ""}
        onChange={(event) => setPropertyId(event.target.value || null)}
        className="rounded-xl border border-border bg-surface-card px-3 py-2 text-sm font-medium text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
      >
        <option value="">{t("propertyFilter.all")}</option>
        {properties.map((property) => (
          <option key={property.id} value={property.id}>
            {property.name}
          </option>
        ))}
      </select>
      {accessRevoked && (
        <p className="text-xs text-status-critical">{t("propertyFilter.accessRevoked")}</p>
      )}
    </div>
  );
}
