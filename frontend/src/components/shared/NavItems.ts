import {
  AlertTriangle,
  LayoutDashboard,
  Menu,
  Receipt,
  Settings,
  Users,
} from "lucide-react";

// Placeholder nav lists — FE-01 replaces these with items filtered by the
// permission matrix from /auth/me/ (invariant F8), not a hardcoded set.

/** Desktop sidebar — every section gets its own entry. */
export const SIDEBAR_NAV_ITEMS = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/residents", label: "Residents", icon: Users },
  { href: "/complaints", label: "Complaints", icon: AlertTriangle },
  { href: "/financials", label: "Financials", icon: Receipt },
  { href: "/settings", label: "Settings", icon: Settings },
] as const;

/** Mobile tab bar — capped at 4 slots; the rest live behind "More". */
export const BOTTOM_NAV_ITEMS = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/residents", label: "Residents", icon: Users },
  { href: "/complaints", label: "Complaints", icon: AlertTriangle },
  { href: "/more", label: "More", icon: Menu },
] as const;
