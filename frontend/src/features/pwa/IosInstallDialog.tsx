"use client";

import { useTranslations } from "next-intl";
import { Dialog } from "@/components/ui/Dialog";

interface IosInstallDialogProps {
  open: boolean;
  onClose: () => void;
  /** In-app browsers (WhatsApp, Instagram, …) can't add to the Home Screen at all. */
  inApp: boolean;
}

/** iOS has no install prompt, so this walks the user through Share -> Add to Home Screen. */
export function IosInstallDialog({ open, onClose, inApp }: IosInstallDialogProps) {
  const t = useTranslations("pwa.install.ios");

  return (
    <Dialog open={open} onClose={onClose} title={t("title")}>
      {inApp ? (
        <p className="text-sm text-ink-muted">{t("openInSafari")}</p>
      ) : (
        <ol className="list-decimal space-y-2 ps-5 text-sm text-ink">
          <li>{t("step1")}</li>
          <li>{t("step2")}</li>
          <li>{t("step3")}</li>
        </ol>
      )}
      <button
        type="button"
        onClick={onClose}
        className="w-full cursor-pointer rounded-xl bg-accent px-4 py-2.5 text-sm font-semibold text-ink-inverse transition-colors hover:bg-accent-hover"
      >
        {t("done")}
      </button>
    </Dialog>
  );
}
