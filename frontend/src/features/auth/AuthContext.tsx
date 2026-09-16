"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { getCurrentUser, type CurrentUser } from "@/lib/api";
import { hasPermission as checkPermission } from "@/lib/permissions";

interface AuthContextValue {
  /** null while loading, or once loading has finished with no valid session. */
  user: CurrentUser | null;
  permissions: string[];
  isLoading: boolean;
  hasPermission: (permission: string) => boolean;
  /** Re-fetch /auth/me/ — e.g. after profile/language updates. */
  refetch: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

/**
 * Fetches `/auth/me/` once (and on refetch()) and exposes the current user +
 * permission matrix to every descendant. In-memory only — the session token
 * itself still lives in localStorage via lib/api.ts's temporary direct client
 * (see docs/frontend-plan.md §3.1/§11 Decisions; not yet the httpOnly-cookie
 * BFF proxy). apiFetch() already redirects to /login and clears storage on a
 * 401 that survives refresh, so a failed fetch here just leaves user = null
 * for the route guard to act on.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const fetchUser = useCallback(() => {
    return getCurrentUser()
      .then((me) => setUser(me))
      .catch(() => setUser(null))
      .finally(() => setIsLoading(false));
  }, []);

  useEffect(() => {
    fetchUser();
  }, [fetchUser]);

  const permissions = user?.permissions ?? [];

  const value: AuthContextValue = {
    user,
    permissions,
    isLoading,
    hasPermission: (permission: string) => checkPermission(permissions, permission),
    refetch: fetchUser,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
