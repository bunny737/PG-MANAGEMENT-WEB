import { Bell, Plus } from "lucide-react";

export function DesktopHeader() {
  return (
    <header className="sticky top-0 z-20 flex items-center justify-between border-b border-border/80 bg-surface-card/85 backdrop-blur-md px-8 py-5 transition-all">
      <div>
        <h1 className="font-display text-2xl font-bold tracking-tight text-ink">Overview</h1>
        <p className="text-xs font-medium text-ink-muted">
          Welcome back, here&apos;s today&apos;s summary.
        </p>
      </div>
      <div className="flex items-center gap-3">
        <button
          type="button"
          aria-label="Notifications"
          className="relative flex size-10 items-center justify-center rounded-xl border border-border bg-surface-card text-ink-muted shadow-2xs transition-all hover:bg-surface-subtle hover:text-ink hover:border-border-strong"
        >
          <Bell className="size-4.5" aria-hidden />
          <span className="absolute top-2 right-2.5 size-2 rounded-full bg-status-critical ring-2 ring-surface-card" />
        </button>
        <button
          type="button"
          className="flex items-center gap-2 rounded-xl bg-accent px-4 py-2.5 text-xs font-semibold text-ink-inverse shadow-sm transition-all hover:bg-accent-hover hover:shadow-md active:scale-[0.98]"
        >
          <Plus className="size-4" aria-hidden />
          Add Resident
        </button>
      </div>
    </header>
  );
}
