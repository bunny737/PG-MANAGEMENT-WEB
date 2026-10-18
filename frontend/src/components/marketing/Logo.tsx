import Link from "next/link";
import { Building2 } from "lucide-react";
import { cn } from "@/lib/utils";

/** Placeholder wordmark: the same accent square + building mark the app shell uses.
 * Replace with the final logo SVG when one exists. */
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
      <span className="flex size-9 items-center justify-center rounded-xl bg-accent text-ink-inverse shadow-sm">
        <Building2 className="size-5" aria-hidden="true" />
      </span>
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
