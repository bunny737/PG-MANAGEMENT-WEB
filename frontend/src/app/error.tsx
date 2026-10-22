"use client";

import { useEffect } from "react";
import { useTranslations } from "next-intl";
import { ErrorView } from "@/components/shared/ErrorView";

// Catches a render crash anywhere below the root layout, so the page keeps the app's own look
// (and language) instead of Next's default "Application error" screen.
export default function Error({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const t = useTranslations("errors");

  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <ErrorView
      copy={{ title: t("title"), body: t("body"), retry: t("retry"), home: t("home") }}
      reference={error.digest ? t("reference", { code: error.digest }) : undefined}
      onRetry={reset}
    />
  );
}
