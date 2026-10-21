"use client";

import React, { useState } from "react";
import { useTranslations } from "next-intl";
import { Loader2, Mail } from "lucide-react";
import { CheckEmailPanel } from "./CheckEmailPanel";
import { useVerificationResend } from "./useVerificationResend";
import { isValidEmail } from "./validation";

interface ResendVerificationPromptProps {
  email?: string;
  /** Let the user type the address (the expired-link page); otherwise `email` is used as given. */
  editable?: boolean;
  showBackToLogin?: boolean;
}

/** A "send me a verification link" action. It only switches to "We sent…" once the request has
 * succeeded, never before. */
export function ResendVerificationPrompt({
  email: initialEmail = "",
  editable = false,
  showBackToLogin = false,
}: ResendVerificationPromptProps) {
  const t = useTranslations("auth");
  const { send, sending, error } = useVerificationResend();
  const [email, setEmail] = useState(initialEmail);
  const [inputError, setInputError] = useState<string | null>(null);
  const [sent, setSent] = useState<{ email: string; at: number } | null>(null);

  if (sent) {
    return <CheckEmailPanel email={sent.email} sentAt={sent.at} showBackToLogin={showBackToLogin} />;
  }

  const handleSend = async (e?: React.FormEvent) => {
    e?.preventDefault();
    const trimmed = email.trim();
    if (!trimmed) {
      setInputError(t("login.errEmailRequired"));
      return;
    }
    if (!isValidEmail(trimmed)) {
      setInputError(t("login.errEmailInvalid"));
      return;
    }
    setInputError(null);
    if (await send(trimmed)) setSent({ email: trimmed, at: Date.now() });
  };

  const message = inputError ?? error;

  return (
    <form onSubmit={handleSend} className="space-y-3" noValidate>
      {editable && (
        <div className="relative">
          <span className="absolute inset-y-0 left-0 flex items-center pl-3.5 text-ink-faint">
            <Mail className="size-4.5" />
          </span>
          <input
            type="email"
            autoComplete="email"
            aria-label={t("login.emailLabel")}
            placeholder={t("login.emailPlaceholder")}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded-xl border border-border bg-surface-card py-2.5 pl-10 pr-4 text-sm text-ink outline-none transition-all focus:ring-4 focus:ring-accent/15 focus:border-accent"
            disabled={sending}
          />
        </div>
      )}
      <button
        type="submit"
        disabled={sending}
        className="flex w-full items-center justify-center rounded-xl border border-accent py-2.5 text-sm font-semibold text-accent hover:bg-accent-soft transition-colors disabled:opacity-60 cursor-pointer"
      >
        {sending ? (
          <>
            <Loader2 className="mr-2 size-4 animate-spin" /> {t("checkEmail.resending")}
          </>
        ) : (
          t("checkEmail.sendLink")
        )}
      </button>
      {message && <p role="alert" className="text-xs text-status-critical">{message}</p>}
    </form>
  );
}
