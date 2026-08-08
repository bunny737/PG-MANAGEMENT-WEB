"use client";

import { usePathname } from "next/navigation";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { BOTTOM_NAV_ITEMS } from "./NavItems";

/** Mobile tab bar (< md) — matches the phone reference mock. SideNav takes
 * over at md+ (see (owner)/layout.tsx). */
export function BottomNav() {
  const pathname = usePathname();

  return (
    <nav className="fixed inset-x-0 bottom-0 z-10 border-t border-border bg-surface-card/95 shadow-[0_-4px_16px_-4px_rgb(11_18_32/0.08)] backdrop-blur-sm md:hidden">
      <div className="mx-auto flex max-w-md items-center justify-around px-2 py-2">
        {BOTTOM_NAV_ITEMS.map((item) => {
          const isActive = pathname.startsWith(item.href);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={isActive ? "page" : undefined}
              className={cn(
                "flex flex-col items-center gap-1 rounded-xl px-3 py-1.5 text-xs font-medium transition-colors",
                isActive
                  ? "bg-accent text-ink-inverse shadow-sm"
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
