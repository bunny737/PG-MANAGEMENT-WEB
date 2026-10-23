"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { ArrowLeft, Loader2, Mail } from "lucide-react";
import { requestPasswordReset } from "@/lib/api";
import { CheckEmailPanel } from "./CheckEmailPanel";
import { useEmailRequest } from "./useEmailRequest";
import { isValidEmail } from "./validation";

const RESET_KIND = "reset" as const;

/** Asks for a password-reset link. "We sent a link" appears only after the request succeeded, and
 * it never claims the address is registered (the backend answers every address alike). */
export function ForgotPasswordForm() {
  const t = useTranslations("auth");
  const { send, sending, error } = useEmailRequest(requestPasswordReset);
  const [email, setEmail] = useState("");
  const [inputError, setInputError] = useState<string | null>(null);
  const [sent, setSent] = useState<{ email: string; at: number } | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const address = email.trim();
    if (!address) {
      setInputError(t("login.errEmailRequired"));
      return;
    }
    if (!isValidEmail(address)) {
      setInputError(t("login.errEmailInvalid"));
      return;
    }
    setInputError(null);
    if (await send(address)) setSent({ email: address, at: Date.now() });
  };

  const message = inputError ?? error;

  return (
    <div className="flex w-full flex-col justify-center px-4 py-12 sm:px-6 md:px-8 lg:w-1/2 xl:w-5/12">
      <div className="mx-auto w-full max-w-md space-y-6">
        <Link
          href="/login"
          className="group inline-flex items-center gap-2 text-sm font-medium text-ink-muted hover:text-ink transition-colors"
        >
          <ArrowLeft className="size-4 transition-transform group-hover:-translate-x-0.5" />
          {t("forgotPassword.backToLogin")}
        </Link>

        {sent ? (
          <CheckEmailPanel email={sent.email} sentAt={sent.at} kind={RESET_KIND} showBackToLogin={false} />
        ) : (
          <>
            <div className="space-y-2">
              <h2 className="text-2xl font-bold tracking-tight text-ink">{t("forgotPassword.title")}</h2>
              <p className="text-sm text-ink-muted">{t("forgotPassword.subtitle")}</p>
            </div>

            <form onSubmit={handleSubmit} className="space-y-4" noValidate>
              <div className="space-y-1.5">
                <label htmlFor="forgot-email" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                  {t("login.emailLabel")}
                </label>
                <div className="relative">
                  <span className="absolute inset-y-0 left-0 flex items-center pl-3.5 text-ink-faint">
                    <Mail className="size-4.5" />
                  </span>
                  <input
                    id="forgot-email"
                    type="email"
                    autoComplete="email"
                    placeholder={t("login.emailPlaceholder")}
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className={`w-full rounded-xl border ${
                      message ? "border-status-critical focus:ring-status-critical/10" : "border-border focus:ring-accent/15 focus:border-accent"
                    } bg-surface-card py-2.5 pl-10 pr-4 text-sm text-ink outline-none transition-all focus:ring-4`}
                    disabled={sending}
                  />
                </div>
                {message && <p role="alert" className="text-xs text-status-critical">{message}</p>}
              </div>

              <button
                type="submit"
                disabled={sending}
                className="flex w-full items-center justify-center rounded-xl bg-accent py-2.5 text-sm font-semibold text-ink-inverse hover:bg-accent-hover transition-colors disabled:opacity-50 cursor-pointer"
              >
                {sending ? (
                  <>
                    <Loader2 className="mr-2 size-4.5 animate-spin" /> {t("forgotPassword.sending")}
                  </>
                ) : (
                  t("forgotPassword.submit")
                )}
              </button>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
