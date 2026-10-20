"use client";

import { useEffect } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";

/** Height the FAB takes above the bottom nav; the update toast reads it to stack above the FAB. */
const FAB_STACK = "4.5rem";

interface FabProps {
  href: string;
  label: string;
  icon: React.ReactNode;
  className?: string;
}

/**
 * Extended floating action button (phones only). It sits directly above the bottom nav, and
 * publishes `--fab-stack` while mounted so PwaRegister's toast clears it (nav, then FAB, then toast).
 * The caller decides whether the user may see it (PermissionGate).
 */
export function Fab({ href, label, icon, className }: FabProps) {
  useEffect(() => {
    const root = document.documentElement;
    root.style.setProperty("--fab-stack", FAB_STACK);
    return () => {
      root.style.removeProperty("--fab-stack");
    };
  }, []);

  return (
    <Link
      href={href}
      className={cn(
        "fixed right-4 bottom-[calc(5rem+env(safe-area-inset-bottom)+1rem)] z-10 flex h-14 items-center gap-3 rounded-2xl bg-m3-primary-container px-5 text-base font-medium text-m3-on-primary-container shadow-md transition-shadow active:shadow-sm md:hidden",
        className
      )}
    >
      <span aria-hidden className="flex size-6 items-center justify-center">
        {icon}
      </span>
      {label}
    </Link>
  );
}
