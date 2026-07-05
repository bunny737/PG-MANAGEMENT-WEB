import { AlertTriangle, LayoutDashboard, Menu, Users } from "lucide-react";

// Placeholder nav list — FE-01 replaces this with items filtered by the
// permission matrix from /auth/me/ (invariant F8), not a hardcoded set.
export const NAV_ITEMS = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/residents", label: "Residents", icon: Users },
  { href: "/complaints", label: "Complaints", icon: AlertTriangle },
  { href: "/more", label: "More", icon: Menu },
] as const;
