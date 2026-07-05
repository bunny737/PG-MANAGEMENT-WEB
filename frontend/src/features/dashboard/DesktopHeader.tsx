import { Bell, Plus } from "lucide-react";

export function DesktopHeader() {
  return (
    <header className="flex items-center justify-between border-b border-border px-8 py-6">
      <div>
        <h1 className="text-2xl font-bold text-ink">Overview</h1>
        <p className="text-sm text-ink-muted">
          Welcome back, here&apos;s today&apos;s summary.
        </p>
      </div>
      <div className="flex items-center gap-4">
        <button
          type="button"
          aria-label="Notifications"
          className="relative flex size-10 items-center justify-center rounded-full text-ink-muted hover:bg-surface-page hover:text-ink"
        >
          <Bell className="size-5" aria-hidden />
          <span className="absolute top-2 right-2.5 size-2 rounded-full bg-status-critical" />
        </button>
        <button
          type="button"
          className="flex items-center gap-2 rounded-xl bg-accent px-4 py-2.5 text-sm font-semibold text-ink-inverse transition-colors hover:bg-accent-hover"
        >
          <Plus className="size-4" aria-hidden />
          Add Resident
        </button>
      </div>
    </header>
  );
}
