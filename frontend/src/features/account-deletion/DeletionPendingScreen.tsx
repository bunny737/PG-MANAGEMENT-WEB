"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Trash2 } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { cancelAccountDeletion, clearSession, getCurrentUser, type CurrentUser } from "@/lib/api";
import { postLoginRoute } from "@/lib/permissions";

/** How often a deletion that has started (or got stuck) is re-checked, so the screen follows it. */
const POLL_MS = 30_000;

/**
 * The only screen a locked account can use. It sits outside the (owner) layout on purpose: that
 * layout's nav and background queries are exactly the calls that answer 403 while the account is
 * locked. It calls only GET /auth/me/ and the deletion endpoint, both of which stay open.
 */
export function DeletionPendingScreen() {
  const t = useTranslations("accountDeletion.pending");
  const locale = useLocale();
  const router = useRouter();
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [status, setStatus] = useState<"loading" | "error" | "ready">("loading");
  const [cancelling, setCancelling] = useState(false);
  const [cancelFailed, setCancelFailed] = useState(false);

  const apply = useCallback(
    (me: CurrentUser) => {
      if (!me.deletion) {
        // Cancelled (here or elsewhere): the account is usable again.
        router.replace(postLoginRoute(me));
        return;
      }
      setUser(me);
      setStatus("ready");
    },
    [router]
  );

  // Always asynchronous: the state is only set from the promise callbacks.
  const load = useCallback(
    () =>
      getCurrentUser()
        .then(apply)
        .catch(() => setStatus((current) => (current === "ready" ? current : "error"))),
    [apply]
  );

  useEffect(() => {
    void load();
  }, [load]);

  const deletion = user?.deletion ?? null;
  const settled = deletion !== null && deletion.status !== "pending";
  useEffect(() => {
    if (!settled) return;
    const timer = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(timer);
  }, [settled, load]);

  const cancel = async () => {
    setCancelling(true);
    setCancelFailed(false);
    try {
      await cancelAccountDeletion();
      await load();
    } catch {
      setCancelFailed(true);
    } finally {
      setCancelling(false);
    }
  };

  const signOut = async () => {
    await clearSession();
    router.replace("/login");
  };

  let content: React.ReactNode;
  if (status === "loading") {
    content = <p className="text-sm text-ink-muted">{t("loading")}</p>;
  } else if (status === "error" || !deletion || !user) {
    content = (
      <div className="space-y-3">
        <p role="alert" className="text-sm text-status-critical">
          {t("loadFailed")}
        </p>
        <button
          type="button"
          onClick={() => {
            setStatus("loading");
            void load();
          }}
          className="cursor-pointer rounded-xl border border-border px-4 py-2 text-xs font-semibold text-ink hover:bg-surface-page"
        >
          {t("retry")}
        </button>
      </div>
    );
  } else {
    const date = new Intl.DateTimeFormat(locale, { dateStyle: "long", timeZone: "Asia/Kolkata" }).format(
      new Date(deletion.scheduled_for)
    );
    const staffOfDeletingBusiness = deletion.scope === "tenant" && user.role !== "owner";
    const title =
      deletion.status === "processing"
        ? t("titleProcessing")
        : deletion.status === "failed"
          ? t("titleFailed")
          : t("titlePending");

    content = (
      <div className="space-y-4">
        <h1 className="text-xl font-bold tracking-tight text-ink">{title}</h1>
        {deletion.status === "pending" && (
          <>
            <p className="text-sm text-ink">
              {staffOfDeletingBusiness
                ? t("staffBody", { date })
                : deletion.scope === "tenant"
                  ? t("ownBusinessBody", { date })
                  : t("ownAccountBody", { date })}
            </p>
            <p className="text-sm text-ink-muted">{t("locked")}</p>
            {deletion.can_cancel ? (
              <>
                <p className="text-sm text-ink-muted">{t("canCancel")}</p>
                <button
                  type="button"
                  onClick={cancel}
                  disabled={cancelling}
                  className="cursor-pointer rounded-xl bg-accent px-4 py-2.5 text-xs font-bold text-ink-inverse transition-colors hover:bg-accent-hover disabled:opacity-60"
                >
                  {cancelling ? t("cancelling") : t("cancel")}
                </button>
                {cancelFailed && (
                  <p role="alert" className="text-xs text-status-critical">
                    {t("cancelFailed")}
                  </p>
                )}
              </>
            ) : (
              staffOfDeletingBusiness && <p className="text-sm text-ink-muted">{t("ownerOnly")}</p>
            )}
          </>
        )}
        {deletion.status === "processing" && <p className="text-sm text-ink">{t("processingBody")}</p>}
        {deletion.status === "failed" && <p className="text-sm text-ink">{t("failedBody")}</p>}
      </div>
    );
  }

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-lg flex-col justify-center px-4 py-10">
      <div className="rounded-2xl border border-border bg-surface-card p-6 shadow-sm">
        <Trash2 className="mb-4 size-6 text-rose-600" aria-hidden />
        {content}
        <div className="mt-6 border-t border-border pt-4">
          <button
            type="button"
            onClick={signOut}
            className="cursor-pointer text-xs font-semibold text-ink-muted hover:text-ink"
          >
            {t("signOut")}
          </button>
        </div>
      </div>
    </main>
  );
}
