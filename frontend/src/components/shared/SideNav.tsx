"use client";

import { usePathname } from "next/navigation";
import Link from "next/link";
import { Building2, LogOut } from "lucide-react";
import { cn } from "@/lib/utils";
import { SIDEBAR_NAV_ITEMS } from "./NavItems";

// TODO(FE-13): replace the hardcoded "Owner Portal / Premium Plan" footer
// with the authenticated user's name/role and the tenant's actual plan name.
export function SideNav() {
  const pathname = usePathname();

  return (
    <nav className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col border-r border-border bg-surface-card md:flex">
      <div className="flex items-center gap-2.5 px-5 py-5">
        <span className="flex size-9 items-center justify-center rounded-xl bg-surface-inverse text-ink-inverse">
          <Building2 className="size-5" aria-hidden />
        </span>
        <span className="text-lg font-bold text-ink">PropManager</span>
      </div>

      <div className="flex flex-1 flex-col gap-1 px-3">
        {SIDEBAR_NAV_ITEMS.map((item) => {
          const isActive = pathname.startsWith(item.href);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors",
                isActive
                  ? "bg-surface-page font-semibold text-ink"
                  : "text-ink-muted hover:bg-surface-page hover:text-ink"
              )}
            >
              <Icon className="size-5" aria-hidden />
              {item.label}
            </Link>
          );
        })}
      </div>

      <div className="flex items-center justify-between border-t border-border px-5 py-4">
        <Link
          href="/profile"
          className="flex items-center gap-3 hover:opacity-85 transition-opacity cursor-pointer"
        >
          <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-surface-inverse text-sm font-semibold text-ink-inverse">
            OP
          </span>
          <div className="flex flex-col">
            <span className="text-sm font-semibold text-ink">Owner Portal</span>
            <span className="text-xs text-ink-faint">Premium Plan</span>
          </div>
        </Link>
        <button
          onClick={() => {
            localStorage.removeItem("isLoggedIn");
            window.location.href = "/login";
          }}
          className="rounded-lg p-1.5 text-ink-muted hover:bg-surface-page hover:text-ink transition-colors cursor-pointer"
          title="Sign Out"
        >
          <LogOut className="size-5" aria-hidden />
        </button>
      </div>
    </nav>
  );
}
