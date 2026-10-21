"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { AlertTriangle, CheckCircle2, Loader2, MailQuestion } from "lucide-react";
import { ApiError, verifyEmail } from "@/lib/api";
import { ResendVerificationPrompt } from "./ResendVerificationPrompt";

type State = "verifying" | "verified" | "invalid" | "missing" | "error";

/** The emailed link carries its token in the URL fragment (`/verify-email#token=…`), which never
 * reaches any server. A `?token=` query is accepted as a fallback for hand-edited links (that one
 * has already been in an access log). */
export function readVerificationToken(location: Pick<Location, "hash" | "search">): string | null {
  const fromHash = new URLSearchParams(location.hash.replace(/^#/, "")).get("token");
  return fromHash || new URLSearchParams(location.search).get("token") || null;
}

/** Confirms the address from the emailed link. Never signs the user in: the link stays valid for
 * days, so it must not work as a login credential. */
export function VerifyEmail() {
  const t = useTranslations("auth");
  const [state, setState] = useState<State>("verifying");
  const tokenRef = useRef<string | null>(null);
  const started = useRef(false);

  const submit = useCallback(async () => {
    const token = tokenRef.current;
    if (!token) {
      setState("missing");
      return;
    }
    setState("verifying");
    try {
      await verifyEmail(token);
      setState("verified");
    } catch (err) {
      // This endpoint does one thing, so any 400 means the link is invalid or expired.
      setState(err instanceof ApiError && err.status === 400 ? "invalid" : "error");
    }
  }, []);

  useEffect(() => {
    // Strict Mode runs effects twice in development; the ref keeps it to one POST.
    if (started.current) return;
    started.current = true;
    tokenRef.current = readVerificationToken(window.location);
    if (tokenRef.current) {
      // Out of the address bar and history right away. history.replaceState (not router.replace)
      // so Next.js doesn't navigate and remount this component mid-request.
      window.history.replaceState(null, "", "/verify-email");
    }
    void submit();
  }, [submit]);

  return (
    <div className="flex w-full flex-col justify-center px-4 py-12 sm:px-6 md:px-8 lg:w-1/2 xl:w-5/12">
      <div className="mx-auto w-full max-w-md space-y-6">
        {state === "verifying" && (
          <div className="flex items-center gap-3 text-sm text-ink-muted" role="status">
            <Loader2 className="size-5 animate-spin" /> {t("verifyEmail.verifying")}
          </div>
        )}

        {state === "verified" && (
          <div className="rounded-xl border border-emerald-100 bg-emerald-50/50 p-6 text-center space-y-4">
            <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-emerald-100 text-emerald-600">
              <CheckCircle2 className="size-6" />
            </div>
            <div className="space-y-1">
              <h2 className="text-lg font-bold text-ink">{t("verifyEmail.successTitle")}</h2>
              <p className="text-sm text-ink-muted">{t("verifyEmail.successBody")}</p>
            </div>
            <Link
              href="/login"
              className="block w-full rounded-xl bg-accent py-2.5 text-sm font-semibold text-ink-inverse hover:bg-accent-hover transition-colors"
            >
              {t("verifyEmail.signIn")}
            </Link>
          </div>
        )}

        {(state === "invalid" || state === "missing") && (
          <div className="space-y-5">
            <div className="flex items-start gap-3">
              <MailQuestion className="mt-0.5 size-6 shrink-0 text-status-critical" />
              <div className="space-y-1">
                <h2 className="text-lg font-bold text-ink">
                  {state === "invalid" ? t("verifyEmail.invalidTitle") : t("verifyEmail.noTokenTitle")}
                </h2>
                <p className="text-sm text-ink-muted">
                  {state === "invalid" ? t("verifyEmail.invalidBody") : t("verifyEmail.noTokenBody")}
                </p>
              </div>
            </div>
            <ResendVerificationPrompt editable showBackToLogin />
          </div>
        )}

        {state === "error" && (
          <div className="space-y-4">
            <div className="flex items-start gap-3">
              <AlertTriangle className="mt-0.5 size-6 shrink-0 text-status-critical" />
              <p role="alert" className="text-sm text-ink-muted">{t("login.errServerUnreachable")}</p>
            </div>
            <button
              type="button"
              onClick={() => void submit()}
              className="w-full rounded-xl bg-accent py-2.5 text-sm font-semibold text-ink-inverse hover:bg-accent-hover transition-colors cursor-pointer"
            >
              {t("verifyEmail.retry")}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
