"use client";

import type { ReactNode } from "react";
import { useAuth } from "@/features/auth/AuthContext";

interface PermissionGateProps {
  /** A key from apps/core/roles.py's PERMISSION_MATRIX, e.g. "manage_invoices". */
  permission: string;
  children: ReactNode;
  /** Rendered instead of children when the permission is absent. Defaults to nothing. */
  fallback?: ReactNode;
}

/**
 * Conditionally renders `children` based on the current user's permission
 * matrix from `/auth/me/` — never inferred from role name (invariant F8,
 * docs/frontend-plan.md). Renders nothing while the session is still loading
 * to avoid a flash of content the user turns out not to have.
 */
export function PermissionGate({ permission, children, fallback = null }: PermissionGateProps) {
  const { hasPermission, isLoading } = useAuth();
  if (isLoading) return null;
  return hasPermission(permission) ? <>{children}</> : <>{fallback}</>;
}
