"use client";

import { usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import { Building2, LogOut } from "lucide-react";
import { useTranslations } from "next-intl";
import { cn, getInitials } from "@/lib/utils";
import { clearSession } from "@/lib/api";
import { useAuth } from "@/features/auth/AuthContext";
import { useNavItems } from "./NavItems";

// TODO(FE-13): the tenant's actual plan name isn't on /auth/me/ yet — the
// footer shows role instead of plan until subscription data is wired up.
export function SideNav() {
  const pathname = usePathname();
  const router = useRouter();
  const t = useTranslations("common");
  const { user } = useAuth();
  const { sidebarItems } = useNavItems();

  const fullName = [user?.first_name, user?.last_name].filter(Boolean).join(" ").trim();
  const displayName = fullName || user?.email || "";
  const roleLabel = user?.role ? t(`roles.${user.role}`) : "";

  const handleSignOut = () => {
    clearSession();
    router.push("/login");
  };

  return (
    <nav className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col border-r border-border bg-surface-card md:flex">
      <div className="flex items-center gap-2.5 px-5 py-5">
        <span className="flex size-9 items-center justify-center rounded-xl bg-linear-to-br from-accent to-accent-hover text-ink-inverse shadow-sm">
          <Building2 className="size-5" aria-hidden />
        </span>
        <span className="font-display text-lg font-extrabold text-ink">
          {t("appName")}
        </span>
      </div>

      <div className="flex flex-1 flex-col gap-0.5 px-3">
        {sidebarItems.map((item) => {
          const isActive = pathname.startsWith(item.href);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={isActive ? "page" : undefined}
              className={cn(
                // `relative` anchors the active rail; the group lets the icon
                // pick up the accent on hover ahead of the label.
                "group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition-colors",
                isActive
                  ? "bg-accent-soft font-semibold text-accent"
                  : "font-medium text-ink-muted hover:bg-surface-subtle hover:text-ink"
              )}
            >
              {isActive ? (
                <span
                  className="absolute top-2 bottom-2 -left-3 w-1 rounded-r-full bg-accent"
                  aria-hidden
                />
              ) : null}
              <Icon
                className={cn(
                  "size-5 transition-colors",
                  isActive ? "text-accent" : "text-ink-faint group-hover:text-ink"
                )}
                aria-hidden
              />
              {t(item.labelKey)}
            </Link>
          );
        })}
      </div>

      <div className="m-3 flex items-center justify-between gap-2 rounded-xl border border-border bg-surface-subtle p-2.5">
        <Link
          href="/profile"
          className="flex min-w-0 items-center gap-2.5 rounded-lg transition-opacity hover:opacity-80"
        >
          <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-linear-to-br from-surface-inverse-soft to-surface-inverse text-xs font-bold text-ink-inverse">
            {displayName ? getInitials(displayName) : ""}
          </span>
          <div className="flex min-w-0 flex-col">
            <span className="truncate text-sm font-semibold text-ink">
              {displayName}
            </span>
            <span className="truncate text-xs text-ink-faint">{roleLabel}</span>
          </div>
        </Link>
        <button
          onClick={handleSignOut}
          className="shrink-0 cursor-pointer rounded-lg p-1.5 text-ink-faint transition-colors hover:bg-status-critical-soft hover:text-status-critical"
          title={t("sideNav.signOut")}
        >
          <LogOut className="size-4.5" aria-hidden />
        </button>
      </div>
    </nav>
  );
}
