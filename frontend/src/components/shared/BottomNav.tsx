"use client";

import { usePathname } from "next/navigation";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { NAV_ITEMS } from "./NavItems";

/** Always-visible tab bar, matching the reference mock at every viewport
 * width. The bar itself spans the viewport but its items are constrained to
 * the same centered column as the page content (see (owner)/dashboard). */
export function BottomNav() {
  const pathname = usePathname();

  return (
    <nav className="fixed inset-x-0 bottom-0 z-10 border-t border-border bg-surface-card">
      <div className="mx-auto flex max-w-md items-center justify-around px-2 py-2">
        {NAV_ITEMS.map((item) => {
          const isActive = pathname.startsWith(item.href);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex flex-col items-center gap-1 rounded-xl px-3 py-1.5 text-xs font-medium transition-colors",
                isActive
                  ? "bg-accent text-ink-inverse"
                  : "text-ink-muted hover:text-ink"
              )}
            >
              <Icon className="size-5" aria-hidden />
              {item.label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
