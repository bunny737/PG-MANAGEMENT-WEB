import { FileText, Plus } from "lucide-react";

export function QuickActions() {
  return (
    <div className="grid grid-cols-2 gap-3 px-4 md:px-6">
      <button
        type="button"
        className="flex items-center justify-center gap-2 rounded-xl bg-surface-inverse px-4 py-3 text-sm font-semibold text-ink-inverse transition-colors hover:bg-ink"
      >
        <Plus className="size-4" aria-hidden />
        Add Resident
      </button>
      <button
        type="button"
        className="flex items-center justify-center gap-2 rounded-xl border border-accent bg-surface-card px-4 py-3 text-sm font-semibold text-accent transition-colors hover:bg-accent-soft"
      >
        <FileText className="size-4" aria-hidden />
        Generate Invoices
      </button>
    </div>
  );
}
