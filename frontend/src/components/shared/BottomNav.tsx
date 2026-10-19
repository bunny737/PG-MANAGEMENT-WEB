"use client";

import { usePathname } from "next/navigation";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { useSession } from "@/lib/session";
import { SIDEBAR_NAV_ITEMS, MORE_NAV_ITEM } from "./NavItems";

/**
 * Mobile tab bar (< md) — displays first 3 permission-visible items plus a 4th "More" slot.
 */
export function BottomNav() {
  const pathname = usePathname();
  const t = useTranslations("common");
  const { can, ready } = useSession();

  const visibleItems = SIDEBAR_NAV_ITEMS.filter(
    (item) => !item.permission || (ready && can(item.permission))
  );

  const primaryItems = visibleItems.slice(0, 3);
  const bottomBarItems = [...primaryItems, MORE_NAV_ITEM];

  return (
    <nav className="fixed inset-x-0 bottom-0 z-10 border-t border-border bg-surface-card/95 shadow-[0_-4px_16px_-4px_rgb(11_18_32/0.08)] backdrop-blur-sm pb-[env(safe-area-inset-bottom)] ps-[env(safe-area-inset-left)] pe-[env(safe-area-inset-right)] md:hidden">
      <div className="mx-auto flex max-w-md items-center justify-around px-2 py-2">
        {bottomBarItems.map((item) => {
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
              {t(item.labelKey)}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
