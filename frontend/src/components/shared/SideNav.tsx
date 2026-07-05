"use client";

import { usePathname } from "next/navigation";
import Link from "next/link";
import { Building2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { NAV_ITEMS } from "./NavItems";

/** Desktop rail (md+). BottomNav renders the same list on mobile. */
export function SideNav() {
  const pathname = usePathname();

  return (
    <nav className="sticky top-0 hidden h-screen w-56 shrink-0 flex-col gap-1 border-r border-border bg-surface-card p-4 md:flex">
      <div className="mb-4 flex items-center gap-2.5 px-2">
        <span className="flex size-9 items-center justify-center rounded-xl bg-surface-inverse text-ink-inverse">
          <Building2 className="size-5" aria-hidden />
        </span>
        <span className="text-lg font-bold text-ink">PropManager</span>
      </div>
      {NAV_ITEMS.map((item) => {
        const isActive = pathname.startsWith(item.href);
        const Icon = item.icon;
        return (
          <Link
            key={item.href}
            href={item.href}
            className={cn(
              "flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors",
              isActive
                ? "bg-accent text-ink-inverse"
                : "text-ink-muted hover:bg-surface-page hover:text-ink"
            )}
          >
            <Icon className="size-5" aria-hidden />
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
