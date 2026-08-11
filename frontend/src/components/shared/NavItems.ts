import {
  AlertTriangle,
  LayoutDashboard,
  Menu,
  Receipt,
  Settings,
  Users,
  Building,
} from "lucide-react";

// Placeholder nav lists — FE-01 replaces these with items filtered by the
// permission matrix from /auth/me/ (invariant F8), not a hardcoded set.

/** Desktop sidebar — every section gets its own entry. */
export const SIDEBAR_NAV_ITEMS = [
  { href: "/dashboard", labelKey: "nav.dashboard", icon: LayoutDashboard },
  { href: "/properties", labelKey: "nav.properties", icon: Building },
  { href: "/residents", labelKey: "nav.residents", icon: Users },
  { href: "/complaints", labelKey: "nav.complaints", icon: AlertTriangle },
  { href: "/financials", labelKey: "nav.financials", icon: Receipt },
  { href: "/settings", labelKey: "nav.settings", icon: Settings },
] as const;

/** Mobile tab bar — capped at 4 slots; the rest live behind "More". */
export const BOTTOM_NAV_ITEMS = [
  { href: "/dashboard", labelKey: "nav.dashboard", icon: LayoutDashboard },
  { href: "/residents", labelKey: "nav.residents", icon: Users },
  { href: "/complaints", labelKey: "nav.complaints", icon: AlertTriangle },
  { href: "/more", labelKey: "nav.more", icon: Menu },
] as const;
