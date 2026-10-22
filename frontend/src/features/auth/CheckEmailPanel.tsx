"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { MailCheck } from "lucide-react";
import { requestPasswordReset, resendVerification } from "@/lib/api";
import { RESEND_COOLDOWN_S } from "./EmailCodeLogin";
import { useEmailRequest } from "./useEmailRequest";

interface CheckEmailPanelProps {
  email: string;
  /** When the current link was sent (ms since epoch); the resend cooldown runs from here. */
  sentAt: number;
  showBackToLogin?: boolean;
  /** Which email was requested: a verification link (default) or a password-reset link. */
  kind?: "verification" | "reset";
}

/** Shown only after an email has actually been requested: "We sent a link to …", with a resend
 * that is held back for RESEND_COOLDOWN_S after each send. The reset wording never says the
 * address is registered. */
export function CheckEmailPanel({ email, sentAt, showBackToLogin = true, kind = "verification" }: CheckEmailPanelProps) {
  const t = useTranslations("auth");
  const reset = kind === "reset";
  const { send, sending, error } = useEmailRequest(reset ? requestPasswordReset : resendVerification);
  const [lastSentAt, setLastSentAt] = useState(sentAt);
  const [now, setNow] = useState(() => Date.now());

  const cooldown = Math.max(0, Math.ceil((lastSentAt + RESEND_COOLDOWN_S * 1000 - now) / 1000));

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setTimeout(() => setNow(Date.now()), 1000);
    return () => clearTimeout(timer);
  }, [cooldown, now]);

  const resend = async () => {
    if (await send(email)) {
      const at = Date.now();
      setLastSentAt(at);
      setNow(at);
    }
  };

  return (
    <div className="rounded-xl border border-emerald-100 bg-emerald-50/50 p-6 text-center space-y-4">
      <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-emerald-100 text-emerald-600">
        <MailCheck className="size-6" />
      </div>
      <div className="space-y-1">
        <h3 className="text-sm font-semibold text-ink">{t("checkEmail.title")}</h3>
        <p className="text-xs text-ink-muted">
          {reset ? t("forgotPassword.sentBody", { email }) : t("checkEmail.body", { email })}
        </p>
      </div>
      <p className="text-xs text-ink-muted">
        {t("checkEmail.noEmail")}{" "}
        {cooldown > 0 ? (
          <span>{t("checkEmail.resendIn", { count: cooldown })}</span>
        ) : (
          <button
            type="button"
            onClick={() => void resend()}
            disabled={sending}
            className="font-semibold text-accent hover:text-accent-hover transition-colors cursor-pointer disabled:opacity-60"
          >
            {sending ? t("checkEmail.resending") : t("checkEmail.resend")}
          </button>
        )}
      </p>
      {error && <p role="alert" className="text-xs text-status-critical">{error}</p>}
      {showBackToLogin && (
        <Link
          href="/login"
          className="block w-full rounded-xl bg-accent py-2 text-xs font-semibold text-ink-inverse hover:bg-accent-hover transition-colors"
        >
          {t("checkEmail.backToLogin")}
        </Link>
      )}
    </div>
  );
}
