"use client";

import { usePathname } from "next/navigation";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { useSession } from "@/lib/session";
import { MOBILE_NAV_ITEMS, MORE_NAV_ITEM } from "./NavItems";

/**
 * Phone navigation bar (< md), Material 3 style like the Android app: Dashboard, Properties,
 * Residents, Billing (each only if the user may open it) and More. The active tab shows a
 * primary-container pill behind its icon.
 */
export function BottomNav() {
  const pathname = usePathname();
  const t = useTranslations("common");
  const { can, ready } = useSession();

  const visibleItems = MOBILE_NAV_ITEMS.filter((item) => !item.permission || (ready && can(item.permission)));
  const bottomBarItems = [...visibleItems, MORE_NAV_ITEM];

  return (
    <nav
      aria-label={t("phone.navigation")}
      className="fixed inset-x-0 bottom-0 z-10 bg-m3-surface-container pb-[env(safe-area-inset-bottom)] ps-[env(safe-area-inset-left)] pe-[env(safe-area-inset-right)] md:hidden"
    >
      <ul className="mx-auto flex h-20 max-w-md items-stretch justify-around px-1">
        {bottomBarItems.map((item) => {
          const isActive = pathname === item.href || pathname.startsWith(`${item.href}/`);
          const Icon = item.icon;
          return (
            <li key={item.href} className="flex min-w-0 flex-1">
              <Link
                href={item.href}
                aria-current={isActive ? "page" : undefined}
                className="flex min-w-0 flex-1 flex-col items-center justify-center gap-1 text-m3-on-surface-variant"
              >
                <span
                  className={cn(
                    "flex h-8 w-16 items-center justify-center rounded-full transition-colors",
                    isActive ? "bg-m3-primary-container text-m3-on-primary-container" : ""
                  )}
                >
                  <Icon className="size-6" aria-hidden />
                </span>
                <span
                  className={cn(
                    "w-full truncate px-0.5 text-center text-xs leading-4",
                    isActive ? "font-bold text-m3-on-surface" : "font-medium"
                  )}
                >
                  {t(item.labelKey)}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
