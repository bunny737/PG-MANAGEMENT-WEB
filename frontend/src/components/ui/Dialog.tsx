"use client";

import { useEffect } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  className?: string;
}

/**
 * Centered modal primitive, extracted from the overlay pattern already in
 * use (ComplaintsDashboard's log-visit dialog, PropertyForm, …) so new
 * dialogs (record payment, reserve a bed, …) don't each re-implement the
 * backdrop/escape/close wiring.
 */
export function Dialog({ open, onClose, title, subtitle, children, className }: DialogProps) {
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
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-on-surface/40 backdrop-blur-sm animate-fade-in"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="dialog-title"
        onClick={(event) => event.stopPropagation()}
        className={cn(
          "w-full max-w-lg space-y-4 rounded-2xl border border-border bg-surface-card p-6 shadow-2xl",
          className
        )}
      >
        <div className="flex items-start justify-between gap-3 border-b border-border pb-3">
          <div>
            <h3 id="dialog-title" className="text-base font-bold text-ink">
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
  );
}
