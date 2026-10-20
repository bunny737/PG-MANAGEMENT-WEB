"use client";

import { useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";

interface MobileTopBarProps {
  /** Large left-aligned title. */
  title: string;
  /** Shows a back arrow. `true` goes back in history; a string navigates there (a deep link has no history to go back to). */
  back?: boolean | string;
  /** Right-hand slot, e.g. the property pill. */
  trailing?: React.ReactNode;
  className?: string;
}

/**
 * Phone top app bar (Material 3 style, matching the Android app). Sticky below the offline
 * banner: the banner publishes its height as `--banner-h` while it is showing.
 */
export function MobileTopBar({ title, back, trailing, className }: MobileTopBarProps) {
  const router = useRouter();
  const t = useTranslations("common.phone");

  return (
    <header
      className={cn(
        "sticky top-[var(--banner-h,0px)] z-20 flex min-h-16 items-center gap-3 bg-m3-surface px-4 pt-[env(safe-area-inset-top)] md:hidden",
        className
      )}
    >
      {back && (
        <button
          type="button"
          aria-label={t("back")}
          onClick={() => (typeof back === "string" ? router.push(back) : router.back())}
          className="-ms-2 flex size-12 shrink-0 cursor-pointer items-center justify-center rounded-full text-m3-on-surface active:bg-m3-surface-container-high"
        >
          <ArrowLeft className="size-6" aria-hidden />
        </button>
      )}
      <h1 className="min-w-0 flex-1 truncate text-[28px] leading-9 font-normal text-m3-on-surface">{title}</h1>
      {trailing}
    </header>
  );
}
