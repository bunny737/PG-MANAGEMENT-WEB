"use client";

import React from "react";
import { useSession } from "@/lib/session";

interface PermissionGateProps {
  permission: string;
  children: React.ReactNode;
}

/**
 * Inline UI gate: renders null if current session lacks the required permission.
 */
export function PermissionGate({ permission, children }: PermissionGateProps) {
  const { ready, can } = useSession();

  if (!ready || !can(permission)) {
    return null;
  }

  return <>{children}</>;
}
