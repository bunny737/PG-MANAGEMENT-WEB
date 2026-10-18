"use client";

import { create } from "zustand";
import { registerSessionCleanup } from "@/lib/sessionPurge";

/**
 * The active-property selection (Dashboard/Billing/Residents/Reports
 * scoping, UX roadmap "active-property scoping"). `null` means "All
 * properties". Persisted in localStorage keyed by *this* signed-in
 * account (tenant + user id), so switching accounts on the same browser
 * never shows account A's selection to account B — `hydrate()` must be
 * called with the new account's ids before the selection is trusted.
 *
 * This store only holds the id and persists it; `useActiveProperty()`
 * (components/shared/PropertyFilter.tsx) is the hook UI code should use —
 * it also validates the id against the account's current `/properties/`
 * list and falls back to "All" with a notice when access was revoked.
 */

const STORAGE_PREFIX = "activeProperty:";

function storageKey(tenantId: string, userId: string) {
  return `${STORAGE_PREFIX}${tenantId}:${userId}`;
}

function readStored(tenantId: string, userId: string): string | null {
  try {
    return localStorage.getItem(storageKey(tenantId, userId));
  } catch {
    return null;
  }
}

function writeStored(tenantId: string, userId: string, propertyId: string | null) {
  try {
    if (propertyId === null) {
      localStorage.removeItem(storageKey(tenantId, userId));
    } else {
      localStorage.setItem(storageKey(tenantId, userId), propertyId);
    }
  } catch {
    // Best-effort persistence; the in-memory value still works for this tab.
  }
}

interface ActivePropertyState {
  /** Set by `hydrate()` once the account is known; null before then. */
  scope: { tenantId: string; userId: string } | null;
  propertyId: string | null;
  /** Reads the saved value for this account (if any) and adopts it. */
  hydrate: (tenantId: string, userId: string) => void;
  setPropertyId: (id: string | null) => void;
  reset: () => void;
}

export const useActivePropertyStore = create<ActivePropertyState>((set, get) => ({
  scope: null,
  propertyId: null,
  hydrate: (tenantId, userId) => {
    const current = get().scope;
    if (current && current.tenantId === tenantId && current.userId === userId) return;
    set({ scope: { tenantId, userId }, propertyId: readStored(tenantId, userId) });
  },
  setPropertyId: (id) => {
    const scope = get().scope;
    if (scope) writeStored(scope.tenantId, scope.userId, id);
    set({ propertyId: id });
  },
  reset: () => set({ scope: null, propertyId: null }),
}));

// Invariant F7: an account switch must not carry the old account's
// selection into memory, even for the instant before the new account's
// hydrate() call lands.
registerSessionCleanup(() => {
  useActivePropertyStore.getState().reset();
});
