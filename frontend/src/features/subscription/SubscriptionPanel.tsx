"use client";

import React, { useEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, CreditCard, Info, LoaderCircle } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  ApiError,
  getSubscription,
  listPlans,
  selectPlan,
  type Plan,
  type Subscription,
} from "@/lib/api";
import { openSubscriptionCheckout } from "@/lib/razorpay";
import { useSession } from "@/lib/session";
import { ProgressBar } from "@/components/shared/ProgressBar";

/** Razorpay confirms a payment by webhook, so after paying we re-read until the plan is active. */
const ACTIVATION_POLLS = 6;
const ACTIVATION_POLL_MS = 2000;

type Notice = { tone: "good" | "info" | "error"; text: string };

const NOTICE_STYLES: Record<Notice["tone"], string> = {
  good: "border-status-good/20 bg-status-good-soft text-status-good",
  info: "border-border bg-surface-page text-ink",
  error: "border-status-critical/20 bg-status-critical-soft text-status-critical",
};

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

const formatDate = (iso: string) =>
  new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });

const daysBetween = (nowMs: number, iso: string) => Math.max(0, Math.ceil((new Date(iso).getTime() - nowMs) / 86_400_000));

const overCap = (plan: Plan, bedCount: number) => plan.max_beds !== null && bedCount > plan.max_beds;

export function SubscriptionPanel() {
  const t = useTranslations("settings.subscription");
  const tCommon = useTranslations("common");
  const { ready, can, user } = useSession();
  const tenantId = user?.tenant_id ?? user?.tenant?.id ?? null;
  const allowed = ready && can("manage_subscription");

  const [plans, setPlans] = useState<Plan[]>([]);
  const [sub, setSub] = useState<Subscription | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [pendingPlan, setPendingPlan] = useState<Plan | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);

  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const rupees = (amount: string | number) => `${tCommon("labels.rupeeSymbol")}${Number(amount).toLocaleString("en-IN")}`;

  const [reloadKey, setReloadKey] = useState(0);
  // Fixed at mount so render stays pure; a trial boundary crossed while this tab is open shows on next visit.
  const [now] = useState(() => Date.now());

  useEffect(() => {
    if (!allowed || !tenantId) return;
    let cancelled = false;
    Promise.all([listPlans(), getSubscription(tenantId)])
      .then(([planList, subscription]) => {
        if (cancelled) return;
        setPlans(planList.filter((plan) => plan.is_active));
        setSub(subscription);
      })
      .catch(() => {
        if (!cancelled) setLoadFailed(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [allowed, tenantId, reloadKey]);

  const retry = () => {
    setLoading(true);
    setLoadFailed(false);
    setReloadKey((key) => key + 1);
  };

  // "Active" alone proves nothing for a tenant already paying on another plan: the change is
  // done only once the server has promoted the plan we are waiting for.
  const waitForActivation = async (id: string, planId: string) => {
    for (let attempt = 0; attempt < ACTIVATION_POLLS; attempt++) {
      const latest = await getSubscription(id);
      if (!mounted.current) return;
      setSub(latest);
      if (latest.tenant_status === "active" && latest.plan?.id === planId && !latest.pending_plan) {
        setNotice({ tone: "good", text: t("noticeActive") });
        return;
      }
      await sleep(ACTIVATION_POLL_MS);
    }
    if (mounted.current) setNotice({ tone: "info", text: t("noticeActivating") });
  };

  const pay = async (subscription: Subscription) => {
    const target = subscription.pending_plan;
    if (!target || !tenantId) return;
    if (!subscription.razorpay_key_id) {
      setNotice({ tone: "info", text: t("noticeNoPayments") });
      return;
    }
    setBusy(true);
    try {
      const outcome = await openSubscriptionCheckout({
        keyId: subscription.razorpay_key_id,
        subscriptionId: subscription.pending_razorpay_subscription_id,
        businessName: user?.tenant?.name ?? target.name,
        description: t("checkoutDescription", { plan: target.name }),
        prefill: {
          name: [user?.first_name, user?.last_name].filter(Boolean).join(" ") || undefined,
          email: user?.email || undefined,
          contact: user?.phone || undefined,
        },
      });
      if (!mounted.current) return;
      if (outcome === "dismissed") {
        setNotice({ tone: "info", text: t("noticeDismissed") });
        return;
      }
      setNotice({ tone: "info", text: t("noticePaid") });
      await waitForActivation(tenantId, target.id);
    } catch {
      if (mounted.current) setNotice({ tone: "error", text: t("errorGeneric") });
    } finally {
      if (mounted.current) setBusy(false);
    }
  };

  const confirmSwitch = async () => {
    if (!pendingPlan || !tenantId) return;
    const plan = pendingPlan;
    setBusy(true);
    setNotice(null);
    try {
      const updated = await selectPlan(tenantId, plan.id);
      if (!mounted.current) return;
      setSub(updated);
      setPendingPlan(null);
      if (plan.pricing_type === "per_bed_monthly") {
        setNotice({ tone: "good", text: t("noticePerBedActive", { plan: plan.name }) });
        setBusy(false);
        return;
      }
      setBusy(false);
      await pay(updated);
    } catch (err) {
      if (!mounted.current) return;
      setNotice({ tone: "error", text: err instanceof ApiError ? err.message : t("errorGeneric") });
      setBusy(false);
    }
  };

  if (ready && !allowed) {
    return <Message icon={<Info className="size-5" />} text={t("ownerOnly")} />;
  }
  const noTenant = allowed && !tenantId;
  if (loading && !noTenant) {
    return (
      <div className="flex items-center justify-center gap-2 py-16 text-sm text-ink-muted">
        <LoaderCircle className="size-5 animate-spin text-accent" />
        {t("loading")}
      </div>
    );
  }
  if (loadFailed || noTenant || !sub) {
    return (
      <div className="space-y-3">
        <Message icon={<AlertTriangle className="size-5" />} text={t("loadError")} />
        <button
          type="button"
          onClick={retry}
          className="rounded-xl border border-border bg-surface-card px-4 py-2 text-xs font-bold text-ink hover:bg-surface-page cursor-pointer"
        >
          {t("retry")}
        </button>
      </div>
    );
  }

  const trialPlan = plans.find((plan) => plan.is_trial_plan);
  const awaitingPlan = sub.pending_plan && sub.pending_razorpay_subscription_id ? sub.pending_plan : null;
  const nearLimit = sub.max_beds !== null && sub.bed_count >= sub.max_beds * 0.9;
  // The server flips a lapsed trial to suspended on its own schedule, so the status can lag the date.
  const trialExpired = Boolean(sub.trial_ends_at) && new Date(sub.trial_ends_at as string).getTime() <= now;

  return (
    <div className="space-y-6 animate-fade-in">
      {notice && (
        <div role="status" className={`flex items-start gap-2.5 rounded-xl border p-3.5 text-xs font-medium ${NOTICE_STYLES[notice.tone]}`}>
          {notice.tone === "good" ? <CheckCircle2 className="size-4 shrink-0" /> : <Info className="size-4 shrink-0" />}
          <p className="leading-relaxed">{notice.text}</p>
        </div>
      )}

      <section className="rounded-2xl border border-border bg-surface-card p-5 shadow-sm space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-wider text-ink-muted">{t("currentPlan")}</p>
            <h2 className="text-lg font-bold text-ink">{sub.plan?.name ?? trialPlan?.name ?? t("statusTrial")}</h2>
          </div>
          <StatusBadge status={sub.tenant_status} label={t(STATUS_KEYS[sub.tenant_status])} />
        </div>

        {sub.tenant_status === "trial" && sub.trial_ends_at && (
          trialExpired ? (
            <p className="text-xs font-medium text-status-critical">{t("trialEnded", { date: formatDate(sub.trial_ends_at) })}</p>
          ) : (
            <p className="text-xs text-ink-muted">
              {t("trialDaysLeft", { count: daysBetween(now, sub.trial_ends_at), date: formatDate(sub.trial_ends_at) })}
              {!sub.plan && trialPlan ? ` ${t("trialLimitsOf", { plan: trialPlan.name })}` : ""}
            </p>
          )
        )}
        {sub.tenant_status === "active" && sub.current_period_end && (
          <p className="text-xs text-ink-muted">{t("nextBilling", { date: formatDate(sub.current_period_end) })}</p>
        )}
        {sub.tenant_status === "payment_failed" && <p className="text-xs text-status-critical">{t("paymentFailedBody")}</p>}
        {sub.tenant_status === "suspended" && <p className="text-xs text-status-critical">{t("suspendedBody")}</p>}
        {sub.tenant_status === "cancelled" && <p className="text-xs text-status-critical">{t("cancelledBody")}</p>}

        {awaitingPlan && (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-status-warn/20 bg-status-warn-soft p-3.5">
            <div>
              <p className="text-xs font-bold text-status-warn">{t("payTitle")}</p>
              <p className="text-xs text-ink-muted">{t("payBody", { plan: awaitingPlan.name })}</p>
            </div>
            <button
              type="button"
              disabled={busy}
              onClick={() => void pay(sub)}
              className="rounded-xl bg-accent px-4 py-2 text-xs font-bold text-ink-inverse hover:bg-accent-hover cursor-pointer disabled:opacity-50"
            >
              {t("payNow")}
            </button>
          </div>
        )}
      </section>

      <section className="rounded-2xl border border-border bg-surface-card p-5 shadow-sm space-y-3">
        <h3 className="text-sm font-bold uppercase tracking-wider text-ink">{t("usageTitle")}</h3>
        {sub.max_beds !== null ? (
          <>
            <p className="text-xs text-ink-muted">{t("bedsOfMax", { used: sub.bed_count, max: sub.max_beds })}</p>
            <ProgressBar percent={sub.max_beds ? (sub.bed_count / sub.max_beds) * 100 : 0} label={t("bedsLabel")} />
          </>
        ) : (
          <p className="text-xs text-ink-muted">{t("bedsUnlimited", { used: sub.bed_count })}</p>
        )}
        {nearLimit && <p className="text-xs font-medium text-status-warn">{t("nearLimit")}</p>}
        {sub.max_properties !== null && (
          <p className="text-xs text-ink-muted">{t("propertiesOfMax", { used: sub.properties_used, max: sub.max_properties })}</p>
        )}
      </section>

      <section className="space-y-3">
        <h3 className="text-sm font-bold uppercase tracking-wider text-ink">{t("plansTitle")}</h3>

        {pendingPlan && (
          <div role="alertdialog" aria-label={t("confirmTitle", { plan: pendingPlan.name })} className="rounded-xl border border-accent/30 bg-accent-soft p-4 space-y-3">
            <p className="text-xs font-semibold text-ink">
              {pendingPlan.pricing_type === "flat_monthly"
                ? t("confirmFlat", { plan: pendingPlan.name, price: rupees(pendingPlan.price_per_month ?? 0) })
                : t("confirmPerBed", { plan: pendingPlan.name })}
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={busy}
                onClick={() => void confirmSwitch()}
                className="rounded-xl bg-accent px-4 py-2 text-xs font-bold text-ink-inverse hover:bg-accent-hover cursor-pointer disabled:opacity-50"
              >
                {busy ? t("working") : t("confirm")}
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => setPendingPlan(null)}
                className="rounded-xl border border-border bg-surface-card px-4 py-2 text-xs font-bold text-ink hover:bg-surface-page cursor-pointer disabled:opacity-50"
              >
                {t("cancel")}
              </button>
            </div>
          </div>
        )}

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {plans.map((plan) => {
            const isCurrent = sub.plan?.id === plan.id;
            const blocked = overCap(plan, sub.bed_count);
            return (
              <article key={plan.id} className="flex flex-col rounded-2xl border border-border bg-surface-card p-5 shadow-sm space-y-3">
                <div className="flex items-center gap-2">
                  <CreditCard className="size-4 text-ink-muted" />
                  <h4 className="text-sm font-bold text-ink">{plan.name}</h4>
                </div>

                {plan.pricing_type === "flat_monthly" ? (
                  <p className="text-2xl font-extrabold tracking-tight text-ink">{t("priceFlat", { price: rupees(plan.price_per_month ?? 0) })}</p>
                ) : (
                  <div className="space-y-1">
                    <p className="text-sm font-bold text-ink">{t("perBedHeading")}</p>
                    {tierLines(plan, rupees, t).map((line) => (
                      <p key={line} className="text-xs text-ink-muted">{line}</p>
                    ))}
                  </div>
                )}

                <p className="text-xs text-ink-muted">
                  {plan.max_beds === null ? t("unlimitedBeds") : t("upToBeds", { count: plan.max_beds })}
                </p>

                <div className="mt-auto space-y-2 pt-1">
                  {blocked && <p className="text-xs text-status-critical">{t("tooManyBeds", { count: sub.bed_count, max: plan.max_beds ?? 0 })}</p>}
                  <button
                    type="button"
                    disabled={isCurrent || blocked || busy}
                    onClick={() => {
                      setNotice(null);
                      setPendingPlan(plan);
                    }}
                    className="w-full rounded-xl bg-accent py-2.5 text-xs font-bold text-ink-inverse hover:bg-accent-hover cursor-pointer disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {isCurrent ? t("currentPlan") : t("choosePlan")}
                  </button>
                </div>
              </article>
            );
          })}
        </div>
      </section>
    </div>
  );
}

const STATUS_KEYS = {
  trial: "statusTrial",
  active: "statusActive",
  payment_failed: "statusPaymentFailed",
  suspended: "statusSuspended",
  cancelled: "statusCancelled",
} as const;

function StatusBadge({ status, label }: { status: Subscription["tenant_status"]; label: string }) {
  const tone =
    status === "active"
      ? "bg-status-good-soft text-status-good"
      : status === "trial"
        ? "bg-accent-soft text-accent"
        : "bg-status-critical-soft text-status-critical";
  return <span className={`rounded-full px-3 py-1 text-[10px] font-bold uppercase tracking-wider ${tone}`}>{label}</span>;
}

function Message({ icon, text }: { icon: React.ReactNode; text: string }) {
  return (
    <div className="flex items-start gap-3 rounded-2xl border border-border bg-surface-card p-5 text-xs text-ink-muted shadow-sm">
      <span className="text-ink-muted">{icon}</span>
      <p className="leading-relaxed">{text}</p>
    </div>
  );
}

/** One line per price step of a per-bed plan, e.g. "Beds 1–50: Free per bed". */
function tierLines(
  plan: Plan,
  rupees: (amount: string | number) => string,
  t: ReturnType<typeof useTranslations>,
): string[] {
  let from = 1;
  return [...plan.bed_tiers]
    .sort((a, b) => (a.up_to_beds ?? Infinity) - (b.up_to_beds ?? Infinity))
    .map((tier) => {
      const price = Number(tier.rate_per_bed) === 0 ? t("free") : t("pricePerBed", { price: rupees(tier.rate_per_bed) });
      const line =
        tier.up_to_beds === null
          ? t("tierFrom", { from, price })
          : t("tierRange", { from, to: tier.up_to_beds, price });
      from = (tier.up_to_beds ?? from) + 1;
      return line;
    });
}
