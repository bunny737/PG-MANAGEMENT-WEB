import { WifiOff } from "lucide-react";
import { getTranslations } from "next-intl/server";
import { RetryButton } from "@/features/pwa/RetryButton";

// Precached by the service worker (app/sw.ts) and shown when a page that isn't saved on the
// device is opened offline. Rendered in the language active when the worker installed.
export default async function OfflinePage() {
  const t = await getTranslations("pwa.offline");

  return (
    <main className="flex min-h-dvh w-full flex-col items-center justify-center gap-4 bg-surface-page px-6 text-center">
      <span className="flex size-14 items-center justify-center rounded-2xl bg-surface-subtle text-ink-muted">
        <WifiOff className="size-7" aria-hidden />
      </span>
      <h1 className="font-display text-xl font-extrabold text-ink">{t("title")}</h1>
      <p className="max-w-sm text-sm text-ink-muted">{t("body")}</p>
      <RetryButton />
    </main>
  );
}
