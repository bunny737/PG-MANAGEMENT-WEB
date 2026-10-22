"use client";

import React, { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { CheckCircle2, Eye, EyeOff, Loader2, Lock, MailQuestion } from "lucide-react";
import { ApiError, confirmPasswordReset } from "@/lib/api";
import { isValidNewPassword } from "./validation";

export interface ResetLink {
  uid: string;
  token: string;
  /** Staff invite: the same link sets the first password. */
  invite: boolean;
}

/** The emailed link carries its credentials in the URL fragment
 * (`/reset-password#uid=…&token=…[&invite=1]`), which never reaches any server or access log. */
export function readResetLink(location: Pick<Location, "hash">): ResetLink | null {
  const params = new URLSearchParams(location.hash.replace(/^#/, ""));
  const uid = params.get("uid");
  const token = params.get("token");
  if (!uid || !token) return null;
  return { uid, token, invite: params.get("invite") === "1" };
}

type Errors = { password?: string; confirm?: string; form?: string };

/** Sets a new password from an emailed link (a reset, or a staff invite's first password). Never
 * signs the user in: the link is an emailed credential, so the only way on is the sign-in page. */
export function ResetPasswordForm() {
  const t = useTranslations("auth");
  // undefined until the URL has been read (it can't be on the server), null when there is no link.
  const [link, setLink] = useState<ResetLink | null | undefined>(undefined);
  const [dead, setDead] = useState(false);
  const [done, setDone] = useState(false);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [errors, setErrors] = useState<Errors>({});
  const [submitting, setSubmitting] = useState(false);
  const started = useRef(false);

  useEffect(() => {
    // Strict Mode runs effects twice in development; the ref keeps the URL read (and strip) to one.
    if (started.current) return;
    started.current = true;
    const found = readResetLink(window.location);
    if (found) {
      // Out of the address bar and history right away. history.replaceState (not router.replace)
      // so Next.js doesn't navigate and remount this component.
      window.history.replaceState(null, "", "/reset-password");
    }
    setLink(found);
  }, []);

  if (link === undefined) return null;

  const invite = link?.invite ?? false;
  const signInHref = invite ? "/login?view=staff" : "/login";

  const shell = (children: React.ReactNode) => (
    <div className="flex w-full flex-col justify-center px-4 py-12 sm:px-6 md:px-8 lg:w-1/2 xl:w-5/12">
      <div className="mx-auto w-full max-w-md space-y-6">{children}</div>
    </div>
  );

  if (done) {
    return shell(
      <div className="rounded-xl border border-emerald-100 bg-emerald-50/50 p-6 text-center space-y-4">
        <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-emerald-100 text-emerald-600">
          <CheckCircle2 className="size-6" />
        </div>
        <div className="space-y-1">
          <h2 className="text-lg font-bold text-ink">{t("resetPassword.successTitle")}</h2>
          <p className="text-sm text-ink-muted">
            {invite ? t("resetPassword.inviteSuccessBody") : t("resetPassword.successBody")}
          </p>
        </div>
        <Link
          href={signInHref}
          className="block w-full rounded-xl bg-accent py-2.5 text-sm font-semibold text-ink-inverse hover:bg-accent-hover transition-colors"
        >
          {t("resetPassword.signIn")}
        </Link>
      </div>
    );
  }

  if (link === null || dead) {
    return shell(
      <div className="space-y-5">
        <div className="flex items-start gap-3">
          <MailQuestion className="mt-0.5 size-6 shrink-0 text-status-critical" />
          <div className="space-y-1">
            <h2 className="text-lg font-bold text-ink">
              {dead ? t("resetPassword.invalidTitle") : t("resetPassword.noLinkTitle")}
            </h2>
            <p className="text-sm text-ink-muted">
              {dead ? t("resetPassword.invalidBody") : t("resetPassword.noLinkBody")}
            </p>
          </div>
        </div>
        <Link
          href="/forgot-password"
          className="block w-full rounded-xl bg-accent py-2.5 text-center text-sm font-semibold text-ink-inverse hover:bg-accent-hover transition-colors"
        >
          {t("resetPassword.requestNew")}
        </Link>
        <Link href="/login" className="block text-center text-sm font-medium text-ink-muted hover:text-ink">
          {t("forgotPassword.backToLogin")}
        </Link>
      </div>
    );
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const next: Errors = {};
    if (!password) next.password = t("login.errPasswordRequired");
    else if (!isValidNewPassword(password)) next.password = t("login.errPasswordLength");
    if (password && confirm !== password) next.confirm = t("signup.errPasswordMismatch");
    if (Object.keys(next).length > 0) {
      setErrors(next);
      return;
    }
    setErrors({});
    setSubmitting(true);
    try {
      await confirmPasswordReset({ uid: link.uid, token: link.token, new_password: password });
      setDone(true);
    } catch (err) {
      if (!(err instanceof ApiError) || err.status === 0) {
        setErrors({ form: t("login.errServerUnreachable") });
      } else if (err.status === 429) {
        setErrors({ form: t("checkEmail.errThrottled") });
      } else if (err.status === 400 && err.fieldError("token")) {
        setDead(true); // the link is used up or expired; a new one is the only way forward
      } else {
        // The backend's password-strength messages arrive already translated.
        const message = err.fieldError("new_password");
        setErrors(message ? { password: message } : { form: t("resetPassword.errFallback") });
      }
    } finally {
      setSubmitting(false);
    }
  };

  const inputClass = (hasError: boolean) =>
    `w-full rounded-xl border ${
      hasError ? "border-status-critical focus:ring-status-critical/10" : "border-border focus:ring-accent/15 focus:border-accent"
    } bg-surface-card py-2.5 pl-10 pr-10 text-sm text-ink outline-none transition-all focus:ring-4`;
  const labelClass = "text-xs font-semibold uppercase tracking-wider text-ink-muted";
  const iconClass = "absolute inset-y-0 left-0 flex items-center pl-3.5 text-ink-faint";

  return shell(
    <>
      <div className="space-y-2">
        <h2 className="text-2xl font-bold tracking-tight text-ink">
          {invite ? t("resetPassword.inviteTitle") : t("resetPassword.title")}
        </h2>
        <p className="text-sm text-ink-muted">
          {invite ? t("resetPassword.inviteSubtitle") : t("resetPassword.subtitle")}
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        <div className="space-y-1.5">
          <label htmlFor="new-password" className={labelClass}>{t("resetPassword.newPasswordLabel")}</label>
          <div className="relative">
            <span className={iconClass}><Lock className="size-4.5" /></span>
            <input
              id="new-password"
              type={showPassword ? "text" : "password"}
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={inputClass(Boolean(errors.password))}
              disabled={submitting}
            />
            <button
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              aria-label={t("signup.togglePassword")}
              className="absolute inset-y-0 right-0 flex items-center pr-3 text-ink-faint hover:text-ink transition-colors cursor-pointer"
            >
              {showPassword ? <EyeOff className="size-4.5" /> : <Eye className="size-4.5" />}
            </button>
          </div>
          {errors.password ? (
            <p role="alert" className="text-xs text-status-critical">{errors.password}</p>
          ) : (
            <p className="text-xs text-ink-faint">{t("resetPassword.passwordHint")}</p>
          )}
        </div>

        <div className="space-y-1.5">
          <label htmlFor="confirm-password" className={labelClass}>{t("signup.confirmPasswordLabel")}</label>
          <div className="relative">
            <span className={iconClass}><Lock className="size-4.5" /></span>
            <input
              id="confirm-password"
              type={showPassword ? "text" : "password"}
              autoComplete="new-password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              className={inputClass(Boolean(errors.confirm))}
              disabled={submitting}
            />
          </div>
          {errors.confirm && <p role="alert" className="text-xs text-status-critical">{errors.confirm}</p>}
        </div>

        {errors.form && <p role="alert" className="text-sm text-status-critical">{errors.form}</p>}

        <button
          type="submit"
          disabled={submitting}
          className="flex w-full items-center justify-center rounded-xl bg-accent py-2.5 text-sm font-semibold text-ink-inverse hover:bg-accent-hover transition-colors disabled:opacity-50 cursor-pointer"
        >
          {submitting ? (
            <>
              <Loader2 className="mr-2 size-4.5 animate-spin" /> {t("resetPassword.submitting")}
            </>
          ) : invite ? (
            t("resetPassword.inviteSubmit")
          ) : (
            t("resetPassword.submit")
          )}
        </button>
      </form>
    </>
  );
}
