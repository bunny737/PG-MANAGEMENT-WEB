import { Search } from "lucide-react";
import { cn } from "@/lib/utils";

interface SearchFieldProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "type"> {
  /** The accessible name; the placeholder is only a hint. */
  label: string;
}

/** Outlined 56px search field with a leading icon. */
export function SearchField({ label, className, ...props }: SearchFieldProps) {
  return (
    <label className={cn("relative block", className)}>
      <span className="sr-only">{label}</span>
      <Search
        className="pointer-events-none absolute start-4 top-1/2 size-6 -translate-y-1/2 text-m3-on-surface-variant"
        aria-hidden
      />
      <input
        type="search"
        className="h-14 w-full rounded-lg border border-m3-on-surface-variant bg-m3-surface ps-14 pe-4 text-base text-m3-on-surface outline-none placeholder:text-m3-on-surface-variant focus:border-2 focus:border-m3-primary"
        {...props}
      />
    </label>
  );
}
