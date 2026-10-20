import { cn } from "@/lib/utils";

/** Outlined phone card: 1px outline-variant border, no heavy shadow (the Android "outlined card"). */
export function TonalCard({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("rounded-2xl border border-m3-outline-variant bg-m3-surface p-4", className)}
      {...props}
    />
  );
}
