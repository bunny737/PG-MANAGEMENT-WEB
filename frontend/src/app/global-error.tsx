"use client";

import { useEffect, useSyncExternalStore } from "react";
import { ErrorView } from "@/components/shared/ErrorView";
import { errorCopyFor, errorReference, pickErrorLocale } from "@/lib/errorCopy";
import "./globals.css";

const subscribe = () => () => {};
const DEFAULT_LOCALE = "en";

function clientLocale() {
  return pickErrorLocale(document.cookie, navigator.languages?.length ? navigator.languages : [navigator.language]);
}

// Renders when the root layout itself crashes, so it replaces that layout: its own <html>/<body>,
// no providers (hence the static catalogs in lib/errorCopy), and the stylesheet imported here.
// The locale is read from the browser; the server snapshot is English, and React re-renders in the
// visitor's language right after hydration.
export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const locale = useSyncExternalStore(subscribe, clientLocale, () => DEFAULT_LOCALE);
  const copy = errorCopyFor(locale);

  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <html lang={locale}>
      <body className="min-h-dvh bg-surface-page text-ink antialiased">
        <ErrorView copy={copy} reference={errorReference(copy, error.digest)} onRetry={reset} />
      </body>
    </html>
  );
}
