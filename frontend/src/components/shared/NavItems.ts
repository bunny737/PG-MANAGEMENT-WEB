import {
  AlertTriangle,
  LayoutDashboard,
  Menu,
  Receipt,
  Settings,
  Users,
  Building,
  UserCheck,
  ClipboardList,
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
  { href: "/dashboard", labelKey: "nav.dashboard", icon: LayoutDashboard, permission: "view_dashboard" },
  { href: "/properties", labelKey: "nav.properties", icon: Building, permission: "view_property_features" },
  { href: "/residents", labelKey: "nav.residents", icon: Users, permission: "view_resident_profile" },
  { href: "/visitors", labelKey: "nav.visitors", icon: ClipboardList, permission: "manage_visitors" },
  { href: "/staff", labelKey: "nav.staff", icon: UserCheck, permission: "manage_staff_accounts" },
  { href: "/complaints", labelKey: "nav.complaints", icon: AlertTriangle, permission: "manage_complaints" },
  { href: "/billing", labelKey: "nav.billing", icon: Receipt, permission: "view_finance" },
  { href: "/settings", labelKey: "nav.settings", icon: Settings, permission: "manage_tenant_settings" },
];

export const MORE_NAV_ITEM: NavItem = {
  href: "/more",
  labelKey: "nav.more",
  icon: Menu,
};
