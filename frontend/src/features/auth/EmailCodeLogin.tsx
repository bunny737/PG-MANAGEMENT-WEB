"use client";

import React, { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { CheckCircle2, KeyRound, Loader2, Mail } from "lucide-react";
import { ApiError, clearSession, loginEmailOtp, requestEmailOtp, type CurrentUser } from "@/lib/api";

/** Seconds before "Resend code" is offered again. The backend also rate-limits per email. */
export const RESEND_COOLDOWN_S = 30;

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const CODE_RE = /^\d{6}$/;

type Step = "email" | "code";

/** The last code request. Held by the parent, which stays mounted when the user switches to the
 * password form and back, so leaving and returning cannot reset the resend cooldown. */
export interface CodeRequest {
  email: string;
  sentAt: number;
}

interface EmailCodeLoginProps {
  /** Roles this login view admits; anyone else is signed straight back out (same as the password flows). */
  expectedRoles: string[];
  initialEmail?: string;
  lastRequest: CodeRequest | null;
  onCodeRequested: (request: CodeRequest) => void;
  roleMismatchMessage: string;
  onSuccess: (me: CurrentUser) => void;
  onUsePassword: () => void;
}

/** The optional "email me a code" sign-in path, shown inside the Owner and Staff login views. */
export function EmailCodeLogin({
  expectedRoles,
  initialEmail = "",
  lastRequest,
  onCodeRequested,
  roleMismatchMessage,
  onSuccess,
  onUsePassword,
}: EmailCodeLoginProps) {
  const t = useTranslations("auth");

  const [step, setStep] = useState<Step>("email");
  const [email, setEmail] = useState(() => initialEmail.trim() || lastRequest?.email || "");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isSuccess, setIsSuccess] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  /** Seconds until `address` may be sent another code (0 for any address not just requested). */
  const cooldownFor = (address: string, at: number) =>
    lastRequest && lastRequest.email === address
      ? Math.max(0, Math.ceil((lastRequest.sentAt + RESEND_COOLDOWN_S * 1000 - at) / 1000))
      : 0;
  const cooldown = step === "code" ? cooldownFor(email, now) : 0;

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setTimeout(() => setNow(Date.now()), 1000);
    return () => clearTimeout(timer);
  }, [cooldown, now]);

  const errorMessage = (err: unknown, fallback: string) => {
    if (!(err instanceof ApiError) || err.status === 0) return t("login.errServerUnreachable");
    if (err.status === 429) return t("login.errTooManyRequests");
    return err.fieldError("detail") ?? fallback;
  };

  const sendCode = async () => {
    const trimmed = email.trim();
    if (!trimmed) {
      setError(t("login.errEmailRequired"));
      return;
    }
    if (!EMAIL_RE.test(trimmed)) {
      setError(t("login.errEmailInvalid"));
      return;
    }
    setError(null);
    setNow(Date.now());
    if (cooldownFor(trimmed, Date.now()) > 0) {
      // Same address still cooling down (e.g. after "Change email" or leaving for the password
      // form): go back to code entry; the code already sent is still the newest one.
      setEmail(trimmed);
      setCode("");
      setStep("code");
      return;
    }
    setIsLoading(true);
    try {
      await requestEmailOtp(trimmed);
      onCodeRequested({ email: trimmed, sentAt: Date.now() });
      setNow(Date.now());
      setEmail(trimmed);
      setCode("");
      setStep("code");
    } catch (err) {
      setError(errorMessage(err, t("login.errEmailInvalid")));
    } finally {
      setIsLoading(false);
    }
  };

  const handleEmailSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    void sendCode();
  };

  const handleCodeSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = code.trim();
    if (!CODE_RE.test(trimmed)) {
      setError(t("login.errOtpCodeInvalid"));
      return;
    }
    setError(null);
    setIsLoading(true);
    try {
      const me = await loginEmailOtp(email, trimmed);
      if (!expectedRoles.includes(me.role)) {
        await clearSession();
        setIsLoading(false);
        setError(roleMismatchMessage);
        return;
      }
      setIsLoading(false);
      setIsSuccess(true);
      onSuccess(me);
    } catch (err) {
      setIsLoading(false);
      setError(errorMessage(err, t("login.errCodeFallback")));
    }
  };

  const inputClass = `w-full rounded-xl border ${
    error ? "border-status-critical focus:ring-status-critical/10" : "border-border focus:ring-accent/15 focus:border-accent"
  } bg-surface-card py-2.5 pl-10 pr-4 text-sm text-ink outline-none transition-all focus:ring-4`;
  const busy = isLoading || isSuccess;

  return (
    <div className="space-y-5">
      {step === "email" ? (
        <form onSubmit={handleEmailSubmit} className="space-y-5" noValidate>
          <p className="text-sm text-ink-muted">{t("login.emailCodeDesc")}</p>
          <div className="space-y-1.5">
            <label htmlFor="email-code-email" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
              {t("login.emailLabel")}
            </label>
            <div className="relative">
              <span className="absolute inset-y-0 left-0 flex items-center pl-3.5 text-ink-faint">
                <Mail className="size-4.5" />
              </span>
              <input
                id="email-code-email"
                type="email"
                autoComplete="email"
                placeholder={t("login.emailPlaceholder")}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className={inputClass}
                disabled={busy}
              />
            </div>
            {error && <p role="alert" className="text-xs text-status-critical">{error}</p>}
          </div>

          <button
            type="submit"
            disabled={busy}
            className="flex w-full items-center justify-center rounded-xl bg-accent py-3 text-sm font-semibold text-ink-inverse transition-all duration-300 hover:bg-accent-hover active:scale-[0.98] disabled:opacity-60 disabled:pointer-events-none cursor-pointer"
          >
            {isLoading ? (
              <>
                <Loader2 className="mr-2 size-4.5 animate-spin" /> {t("login.sendingOtp")}
              </>
            ) : (
              t("login.sendOtp")
            )}
          </button>
        </form>
      ) : (
        <form onSubmit={handleCodeSubmit} className="space-y-5" noValidate>
          <div className="rounded-xl border border-border bg-surface-subtle p-3 text-xs text-ink-muted">
            {t("login.codeSentNotice", { email })}
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <label htmlFor="email-code" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                {t("login.otpCodeLabel")}
              </label>
              <button
                type="button"
                onClick={() => {
                  setStep("email");
                  setCode("");
                  setError(null);
                }}
                disabled={busy}
                className="text-xs font-semibold text-accent hover:text-accent-hover transition-colors cursor-pointer disabled:opacity-60"
              >
                {t("login.changeEmail")}
              </button>
            </div>
            <div className="relative">
              <span className="absolute inset-y-0 left-0 flex items-center pl-3.5 text-ink-faint">
                <KeyRound className="size-4.5" />
              </span>
              <input
                id="email-code"
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                placeholder={t("login.otpCodePlaceholder")}
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                className={`${inputClass} tracking-[0.3em]`}
                disabled={busy}
                autoFocus
              />
            </div>
            {error && <p role="alert" className="text-xs text-status-critical">{error}</p>}
          </div>

          <button
            type="submit"
            disabled={busy}
            className={`flex w-full items-center justify-center rounded-xl py-3 text-sm font-semibold transition-all duration-300 ${
              isSuccess
                ? "bg-emerald-500 text-white"
                : "bg-accent text-ink-inverse hover:bg-accent-hover active:scale-[0.98]"
            } disabled:opacity-60 disabled:pointer-events-none cursor-pointer`}
          >
            {isLoading ? (
              <>
                <Loader2 className="mr-2 size-4.5 animate-spin" /> {t("login.verifying")}
              </>
            ) : isSuccess ? (
              <>
                <CheckCircle2 className="mr-2 size-4.5 animate-bounce" /> {t("login.success")}
              </>
            ) : (
              t("login.verifySubmit")
            )}
          </button>

          <p className="text-center text-xs text-ink-muted">
            {t("login.noCode")}{" "}
            {cooldown > 0 ? (
              <span>{t("login.resendCountdown", { count: cooldown })}</span>
            ) : (
              <button
                type="button"
                onClick={() => void sendCode()}
                disabled={busy}
                className="font-semibold text-accent hover:text-accent-hover transition-colors cursor-pointer disabled:opacity-60"
              >
                {t("login.resendCode")}
              </button>
            )}
          </p>
        </form>
      )}

      <button
        type="button"
        onClick={onUsePassword}
        disabled={busy}
        className="w-full text-center text-sm font-semibold text-accent hover:text-accent-hover transition-colors cursor-pointer disabled:opacity-60"
      >
        {t("login.usePassword")}
      </button>
    </div>
  );
}
