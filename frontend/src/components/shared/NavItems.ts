import {
  AlertTriangle,
  LayoutDashboard,
  Menu,
  Receipt,
  Settings,
  Users,
  Building,
  UserCheck,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  href: string;
  labelKey: string;
  icon: LucideIcon;
  permission?: string;
}

/** Desktop sidebar — gated by permission matrix where applicable. */
export const SIDEBAR_NAV_ITEMS: readonly NavItem[] = [
  { href: "/dashboard", labelKey: "nav.dashboard", icon: LayoutDashboard },
  { href: "/properties", labelKey: "nav.properties", icon: Building },
  { href: "/residents", labelKey: "nav.residents", icon: Users },
  { href: "/staff", labelKey: "nav.staff", icon: UserCheck, permission: "manage_staff_accounts" },
  { href: "/complaints", labelKey: "nav.complaints", icon: AlertTriangle },
  { href: "/financials", labelKey: "nav.financials", icon: Receipt },
  { href: "/settings", labelKey: "nav.settings", icon: Settings },
];

/** Mobile tab bar — capped at 4 slots; the rest live behind "More". */
export const BOTTOM_NAV_ITEMS = [
  { href: "/dashboard", labelKey: "nav.dashboard", icon: LayoutDashboard },
  { href: "/residents", labelKey: "nav.residents", icon: Users },
  { href: "/complaints", labelKey: "nav.complaints", icon: AlertTriangle },
  { href: "/more", labelKey: "nav.more", icon: Menu },
] as const;
