import Link from "next/link";
import { cn } from "@/lib/utils";
import { BrandMark } from "@/components/shared/BrandMark";

/** Wordmark: the PGLive app-icon mark plus the brand name. */
export function Logo({
  name,
  homeLabel,
  inverse = false,
}: {
  name: string;
  homeLabel: string;
  inverse?: boolean;
}) {
  return (
    <Link href="/" aria-label={homeLabel} className="inline-flex items-center gap-2.5">
      <BrandMark />
      <span
        className={cn(
          "font-display text-xl font-extrabold tracking-tight",
          inverse ? "text-ink-inverse" : "text-ink"
        )}
      >
        {name}
      </span>
    </Link>
  );
}
