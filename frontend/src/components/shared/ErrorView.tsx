interface ErrorViewProps {
  copy: { title: string; body: string; retry: string; home: string };
  /** Already formatted ("Reference: abc"): lets support find the failure in the logs. */
  reference?: string;
  onRetry: () => void;
}

/** The crash screen. Plain elements only (no router, no providers): it renders when the app
 * around it is already broken, including from app/global-error.tsx, which replaces the layout. */
export function ErrorView({ copy, reference, onRetry }: ErrorViewProps) {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center bg-surface-page px-6 py-12 text-center">
      {/* eslint-disable-next-line @next/next/no-img-element -- no image pipeline guarantee while crashed */}
      <img src="/brand/pglive-logo.png" alt="PGLive" width={132} className="mb-8 h-auto w-[132px]" />
      <h1 className="text-2xl font-extrabold text-ink sm:text-3xl">{copy.title}</h1>
      <p className="mt-3 max-w-md text-base text-ink-muted">{copy.body}</p>
      <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
        <button
          type="button"
          onClick={onRetry}
          className="rounded-xl bg-accent px-6 py-2.5 text-sm font-semibold text-ink-inverse shadow-sm transition-colors hover:bg-accent-hover cursor-pointer"
        >
          {copy.retry}
        </button>
        {/* A plain anchor on purpose: the client router may be the thing that broke. */}
        {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
        <a
          href="/"
          className="rounded-xl border border-border bg-surface-card px-6 py-2.5 text-sm font-semibold text-ink transition-colors hover:bg-surface-subtle"
        >
          {copy.home}
        </a>
      </div>
      {reference && <p className="mt-6 text-xs text-ink-faint">{reference}</p>}
    </main>
  );
}
