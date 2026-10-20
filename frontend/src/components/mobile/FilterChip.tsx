import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

interface FilterChipProps {
  label: string;
  selected: boolean;
  onClick: () => void;
}

/** Material filter chip: selected = primary-container fill with a check; unselected = outlined. */
export function FilterChip({ label, selected, onClick }: FilterChipProps) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onClick}
      className={cn(
        "flex h-12 shrink-0 cursor-pointer items-center gap-2 rounded-xl border px-4 text-base font-medium whitespace-nowrap transition-colors",
        selected
          ? "border-transparent bg-m3-primary-container text-m3-on-primary-container"
          : "border-m3-outline-variant bg-m3-surface text-m3-on-surface-variant active:bg-m3-surface-container-high"
      )}
    >
      {selected && <Check className="size-5" aria-hidden />}
      {label}
    </button>
  );
}
