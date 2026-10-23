"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AlertTriangle } from "lucide-react";
import { useTranslations } from "next-intl";
import { Dialog } from "@/components/ui/Dialog";
import { DELETION_PENDING_ROUTE, type DeletionConfirmMethod } from "@/lib/accountDeletion";
import {
  ApiError,
  getCurrentUser,
  requestAccountDeletion,
  sendAccountDeletionCode,
  type CurrentUser,
} from "@/lib/api";

/** The two ways to confirm that the UI can offer (phone codes need an SMS backend that does not exist). */
const OFFERED_METHODS: readonly DeletionConfirmMethod[] = ["password", "otp_email"];

/**
 * The "Delete account" danger zone on the profile page — the in-app half of Google Play's account
 * deletion requirement. An Owner's request deletes the whole business, so the dialog says so and points
 * at the exports first. Confirming (password or an emailed code) locks the account and lands on the
 * pending screen, where the request can be reviewed and cancelled.
 */
export function DeleteAccountCard() {
  const t = useTranslations("accountDeletion");
  const router = useRouter();
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [open, setOpen] = useState(false);

  const [acknowledged, setAcknowledged] = useState(false);
  const [method, setMethod] = useState<DeletionConfirmMethod | null>(null);
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [sendingCode, setSendingCode] = useState(false);
  const [codeSent, setCodeSent] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getCurrentUser()
      .then((me) => {
        if (!cancelled) setUser(me);
      })
      .catch(() => {
        if (!cancelled) setLoadFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const methods = (user?.deletion_confirm_methods ?? []).filter((m) => OFFERED_METHODS.includes(m));
  const activeMethod = method && methods.includes(method) ? method : (methods[0] ?? null);
  const isOwner = user?.role === "owner";
  const credential = activeMethod === "password" ? password : code.trim();
  const canSubmit = acknowledged && activeMethod !== null && credential.length > 0 && !submitting;

  const close = () => {
    if (submitting) return;
    setOpen(false);
    setAcknowledged(false);
    setPassword("");
    setCode("");
    setError(null);
  };

  const sendCode = async () => {
    setSendingCode(true);
    setError(null);
    try {
      await sendAccountDeletionCode();
      setCodeSent(true);
    } catch (err) {
      setError(err instanceof ApiError && err.status === 429 ? t("dialog.throttled") : t("dialog.codeFailed"));
    } finally {
      setSendingCode(false);
    }
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!canSubmit || !activeMethod) return;
    setSubmitting(true);
    setError(null);
    try {
      await requestAccountDeletion(activeMethod === "password" ? { password } : { otp: code.trim() });
      router.push(DELETION_PENDING_ROUTE);
    } catch (err) {
      // Field messages come from the backend already translated (Accept-Language).
      if (err instanceof ApiError) {
        setError(
          err.status === 429
            ? t("dialog.throttled")
            : (err.fieldError("password") ?? err.fieldError("otp") ?? err.fieldError("detail") ?? t("dialog.failed"))
        );
      } else {
        setError(t("dialog.failed"));
      }
      setSubmitting(false);
    }
  };

  if (!user) {
    return loadFailed ? (
      <p role="alert" className="mt-6 text-xs text-status-critical">
        {t("card.loadFailed")}
      </p>
    ) : null;
  }

  return (
    <section
      aria-labelledby="delete-account-title"
      className="mt-6 rounded-2xl border border-rose-200 bg-surface-card p-5 shadow-sm"
    >
      <h2
        id="delete-account-title"
        className="flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-rose-700"
      >
        <AlertTriangle className="size-4" aria-hidden /> {t("card.title")}
      </h2>
      <p className="mt-2 text-xs text-ink-muted">{isOwner ? t("card.ownerBody") : t("card.staffBody")}</p>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="mt-4 cursor-pointer rounded-xl border border-rose-300 px-4 py-2 text-xs font-bold text-rose-700 transition-colors hover:bg-rose-50"
      >
        {t("card.button")}
      </button>

      <Dialog open={open} onClose={close} title={t("dialog.title")}>
        <form onSubmit={submit} className="space-y-4 text-xs text-ink-muted">
          {isOwner ? (
            <div>
              <p className="font-semibold text-ink">{t("dialog.ownerIntro")}</p>
              <ul className="mt-2 list-disc space-y-1 pl-5">
                {(t.raw("dialog.ownerItems") as string[]).map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
              <p className="mt-3">
                {t("dialog.exportHint")}{" "}
                <Link href="/reports" className="font-semibold text-accent hover:text-accent-hover">
                  {t("dialog.exportLink")}
                </Link>
              </p>
            </div>
          ) : (
            <p className="font-semibold text-ink">{t("dialog.staffIntro")}</p>
          )}
          <p>{t("dialog.waiting")}</p>
          <p>{t("dialog.retained")}</p>

          <label className="flex items-start gap-2 text-ink">
            <input
              type="checkbox"
              checked={acknowledged}
              onChange={(e) => setAcknowledged(e.target.checked)}
              className="mt-0.5"
            />
            <span>{t("dialog.understand")}</span>
          </label>

          {activeMethod === null ? (
            <p role="alert" className="text-status-critical">
              {t("dialog.noMethod")}
            </p>
          ) : (
            <div className="space-y-3">
              {methods.length > 1 && (
                <fieldset className="space-y-1.5">
                  <legend className="font-semibold uppercase tracking-wider text-ink-muted">
                    {t("dialog.methodLabel")}
                  </legend>
                  {methods.map((m) => (
                    <label key={m} className="flex items-center gap-2 text-ink">
                      <input
                        type="radio"
                        name="confirm-method"
                        checked={activeMethod === m}
                        onChange={() => {
                          setMethod(m);
                          setError(null);
                        }}
                      />
                      {t(`dialog.methods.${m as "password" | "otp_email"}`)}
                    </label>
                  ))}
                </fieldset>
              )}

              {activeMethod === "password" ? (
                <div className="space-y-1.5">
                  <label htmlFor="delete-password" className="font-semibold uppercase tracking-wider">
                    {t("dialog.passwordLabel")}
                  </label>
                  <input
                    id="delete-password"
                    type="password"
                    autoComplete="current-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2.5 text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
                  />
                </div>
              ) : (
                <div className="space-y-1.5">
                  <label htmlFor="delete-code" className="font-semibold uppercase tracking-wider">
                    {t("dialog.codeLabel")}
                  </label>
                  <div className="flex gap-2">
                    <input
                      id="delete-code"
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      maxLength={6}
                      value={code}
                      onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                      className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2.5 text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15"
                    />
                    <button
                      type="button"
                      onClick={sendCode}
                      disabled={sendingCode}
                      className="shrink-0 cursor-pointer rounded-xl border border-border px-3 text-xs font-semibold text-ink hover:bg-surface-page disabled:opacity-60"
                    >
                      {sendingCode ? t("dialog.sendingCode") : t("dialog.sendCode")}
                    </button>
                  </div>
                  {codeSent && <p className="text-emerald-700">{t("dialog.codeSent")}</p>}
                </div>
              )}
            </div>
          )}

          {error && (
            <p role="alert" className="text-status-critical">
              {error}
            </p>
          )}

          <div className="flex flex-col-reverse gap-2 pt-1 sm:flex-row sm:justify-end">
            <button
              type="button"
              onClick={close}
              disabled={submitting}
              className="cursor-pointer rounded-xl border border-border px-4 py-2.5 text-xs font-semibold text-ink hover:bg-surface-page"
            >
              {t("dialog.keep")}
            </button>
            <button
              type="submit"
              disabled={!canSubmit}
              className="cursor-pointer rounded-xl bg-rose-600 px-4 py-2.5 text-xs font-bold text-white transition-colors hover:bg-rose-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting ? t("dialog.submitting") : t("dialog.submit")}
            </button>
          </div>
        </form>
      </Dialog>
    </section>
  );
}
