import {
  AlertTriangle,
  LayoutDashboard,
  Menu,
  Receipt,
  Settings,
  Users,
  Building,
  type LucideIcon,
} from "lucide-react";
import { useAuth } from "@/features/auth/AuthContext";

export interface NavItem {
  href: string;
  labelKey: string;
  icon: LucideIcon;
  /**
   * Permission key from apps/core/roles.py's PERMISSION_MATRIX required to
   * see this item. Omit for items visible to every authenticated user in
   * this route group (e.g. Dashboard) — never gate on role name directly.
   */
  permission?: string;
}

/** Desktop sidebar (Owner + Manager portal) — filtered at render time by
 * useNavItems() against the permission matrix from /auth/me/ (invariant F8),
 * not hardcoded per role. */
export const SIDEBAR_NAV_ITEMS: NavItem[] = [
  { href: "/dashboard", labelKey: "nav.dashboard", icon: LayoutDashboard },
  { href: "/properties", labelKey: "nav.properties", icon: Building, permission: "manage_properties" },
  { href: "/residents", labelKey: "nav.residents", icon: Users, permission: "manage_residents" },
  { href: "/complaints", labelKey: "nav.complaints", icon: AlertTriangle, permission: "manage_complaints" },
  { href: "/financials", labelKey: "nav.financials", icon: Receipt, permission: "manage_invoices" },
  { href: "/settings", labelKey: "nav.settings", icon: Settings, permission: "manage_tenant_settings" },
];

/** Mobile tab bar — capped at 4 slots; the rest live behind "More". */
export const BOTTOM_NAV_ITEMS: NavItem[] = [
  { href: "/dashboard", labelKey: "nav.dashboard", icon: LayoutDashboard },
  { href: "/residents", labelKey: "nav.residents", icon: Users, permission: "manage_residents" },
  { href: "/complaints", labelKey: "nav.complaints", icon: AlertTriangle, permission: "manage_complaints" },
  { href: "/more", labelKey: "nav.more", icon: Menu },
];

function filterByPermission(items: NavItem[], hasPermission: (permission: string) => boolean) {
  return items.filter((item) => !item.permission || hasPermission(item.permission));
}

/** Permission-filtered nav items for the current user. Reads the matrix from
 * AuthContext — visibility is never inferred from role name (invariant F8). */
export function useNavItems() {
  const { hasPermission } = useAuth();
  return {
    sidebarItems: filterByPermission(SIDEBAR_NAV_ITEMS, hasPermission),
    bottomNavItems: filterByPermission(BOTTOM_NAV_ITEMS, hasPermission),
  };
}
