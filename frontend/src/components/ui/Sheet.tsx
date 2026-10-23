"use client";

import { useEffect } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

interface SheetProps {
  open: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  className?: string;
}

/**
 * Right-side slide-over primitive (the expense add/edit sheet, the
 * receipt detail, …), extracted from ComplaintsDashboard's detail panel
 * so new sheets don't each re-implement the backdrop/escape wiring.
 */
export function Sheet({ open, onClose, title, subtitle, children, className }: SheetProps) {
  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-end bg-on-surface/40 backdrop-blur-sm animate-fade-in"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="sheet-title"
        onClick={(event) => event.stopPropagation()}
        className={cn(
          "flex h-full w-full max-w-xl flex-col justify-between space-y-6 overflow-y-auto border-l border-border bg-surface-card px-6 pt-6 pb-[max(1.5rem,env(safe-area-inset-bottom))] shadow-2xl",
          className
        )}
      >
        <div className="space-y-6">
          <div className="flex items-start justify-between gap-3 border-b border-border pb-4">
            <div>
              <h3 id="sheet-title" className="text-base font-bold text-ink">
                {title}
              </h3>
              {subtitle && <p className="mt-0.5 text-xs text-ink-muted">{subtitle}</p>}
            </div>
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg p-1 text-ink-muted transition-colors hover:bg-surface-page cursor-pointer"
            >
              <X className="size-4" aria-hidden />
            </button>
          </div>
          {children}
        </div>
      </div>
    </div>
  );
}
