import { Bell, Building2 } from "lucide-react";

export function DashboardHeader() {
  return (
    <header className="flex items-center justify-between px-4 py-4 md:px-6">
      <div className="flex items-center gap-2.5">
        <span className="flex size-9 items-center justify-center rounded-xl bg-surface-inverse text-ink-inverse">
          <Building2 className="size-5" aria-hidden />
        </span>
        <span className="text-lg font-bold text-ink">PropManager</span>
      </div>
      <button
        type="button"
        aria-label="Notifications"
        className="flex size-9 items-center justify-center rounded-full text-ink-muted hover:bg-surface-card hover:text-ink"
      >
        <Bell className="size-5" aria-hidden />
      </button>
    </header>
  );
}
