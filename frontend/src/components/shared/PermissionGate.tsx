"use client";

import React from "react";
import { type AccessRule, hasAccess } from "@/lib/permissions";
import { useSession } from "@/lib/session";

type PermissionGateProps = AccessRule & {
  children: React.ReactNode;
};

/**
 * Inline UI gate: renders null if current session lacks the required
 * access. Takes a single `permission`, or `anyOf`/`allOf` for a field
 * whose visibility depends on more than one permission (e.g. a card that
 * needs both view_finance and view_expenses).
 */
export function PermissionGate({ children, ...rule }: PermissionGateProps) {
  const { ready, can } = useSession();

  if (!ready || !hasAccess(can, rule)) {
    return null;
  }

  return <>{children}</>;
}
