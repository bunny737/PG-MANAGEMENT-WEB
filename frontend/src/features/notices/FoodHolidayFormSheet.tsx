"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { Sheet } from "@/components/ui/Sheet";
import {
  ApiError,
  createFoodHoliday,
  type FoodHoliday,
  type FoodHolidayPayload,
  getPropertySettings,
  isUUID,
  listProperties,
  updateFoodHoliday,
} from "@/lib/api";
import { compareMoney } from "@/lib/money";
import { queryKeys } from "@/lib/queryKeys";
import { afterFoodHolidayChange } from "@/lib/refresh";
import { useSession } from "@/lib/session";
import { dayCount, MAX_HOLIDAY_DAYS, RATE_PATTERN } from "./helpers";

const INPUT =
  "w-full rounded-xl border border-border bg-surface-card px-3 py-2 text-sm text-ink outline-none focus:border-accent focus:ring-4 focus:ring-accent/15 disabled:opacity-60";
const LABEL = "text-xs font-semibold uppercase tracking-wider text-ink-muted";
const FIELDS = ["property", "name", "start_date", "end_date", "rate_per_day", "adjust_in_bill"] as const;

function sameRate(a: string, b: string): boolean {
  const cmp = compareMoney(a, b);
  return cmp === null ? a === b : cmp === 0;
}

interface FoodHolidayFormSheetProps {
  /** The holiday being edited; omit to add one. */
  initial?: FoodHoliday;
  defaultProperty: string | null;
  onClose: () => void;
  onSaved?: (holiday: FoodHoliday) => void;
}

export function FoodHolidayFormSheet({
  initial: current,
  defaultProperty,
  onClose,
  onSaved,
}: FoodHolidayFormSheetProps) {
  const t = useTranslations("notices.holidayForm");
  // The holiday as it was when the sheet opened. The fields start from it and "what changed" is measured
  // against it, never against `current`: a background refresh (another manager changed the rate) replaces
  // `current` but not what the user is looking at, and a save must not send that stale value back.
  const [initial] = useState(current);
  const { can } = useSession();
  const creating = !initial;
  // The bill-adjustment switch and rate are finance: the backend rejects them without manage_invoices,
  // and the rate is withheld from anyone without view_finance.
  const canAdjust = can("manage_invoices") && can("view_finance");
  const canReadSettings = can("manage_property_settings");
  // Locking is the one thing read live: it can start while the sheet is open, and a locked holiday's
  // dates, adjustment and rate are neither editable nor sent.
  const locked = !!current?.is_locked;
  // A redacted holiday has no rate_per_day key at all; there is then nothing to show or send.
  const rateAvailable = creating || (!!initial && "rate_per_day" in initial);

  const { data: properties = [] } = useQuery({ queryKey: queryKeys.properties.list, queryFn: listProperties });

  const [property, setProperty] = useState(initial?.property ?? defaultProperty ?? "");
  const [name, setName] = useState(initial?.name ?? "");
  const [startDate, setStartDate] = useState(initial?.start_date ?? "");
  const [endDate, setEndDate] = useState(initial?.end_date ?? "");
  const [adjust, setAdjust] = useState(initial?.adjust_in_bill ?? false);
  const [rate, setRate] = useState(initial?.rate_per_day ?? "");
  const [rateTouched, setRateTouched] = useState(false);
  const [postNotice, setPostNotice] = useState(true);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);

  // The property's default rate pre-fills a NEW holiday only. Editing never reads the settings: an
  // existing holiday keeps its own saved rate, whatever the default is now.
  const settingsQuery = useQuery({
    queryKey: queryKeys.properties.settings(property),
    queryFn: () => getPropertySettings(property),
    enabled: creating && canAdjust && canReadSettings && isUUID(property),
  });
  const defaultRate = creating ? (settingsQuery.data?.food_charge_per_day ?? "") : "";
  // Derived, not copied into state by an effect: the settings of the property chosen NOW can never lose to a
  // late response for another one, and a rate the user typed is never overwritten.
  const shownRate = rateTouched || !creating ? rate : defaultRate;
  const settingsLoaded = creating && settingsQuery.isSuccess;

  const days = dayCount(startDate, endDate);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const next: Record<string, string> = {};
    if (creating && !property) next.property = t("propertyRequired");
    if (!name.trim()) next.name = t("nameRequired");
    if (!startDate) next.start_date = t("startRequired");
    if (!endDate) next.end_date = t("endRequired");
    if (startDate && endDate) {
      if (days === 0) next.end_date = t("endBeforeStart");
      else if (days > MAX_HOLIDAY_DAYS) next.end_date = t("tooLong", { max: MAX_HOLIDAY_DAYS });
    }
    if (adjust && canAdjust && rateAvailable) {
      if (!shownRate) next.rate_per_day = t("rateRequired");
      else if (!RATE_PATTERN.test(shownRate)) next.rate_per_day = t("rateInvalid");
    }
    if (Object.keys(next).length > 0) {
      setErrors(next);
      return;
    }

    const payload: FoodHolidayPayload = {};
    if (initial) {
      // Only what changed, so a redacted or untouched rate is never sent back.
      if (name.trim() !== initial.name) payload.name = name.trim();
      if (!locked) {
        if (startDate !== initial.start_date) payload.start_date = startDate;
        if (endDate !== initial.end_date) payload.end_date = endDate;
        if (canAdjust && adjust !== initial.adjust_in_bill) payload.adjust_in_bill = adjust;
        if (canAdjust && adjust && rateAvailable && !sameRate(shownRate, initial.rate_per_day ?? "")) {
          payload.rate_per_day = shownRate;
        }
      }
      if (Object.keys(payload).length === 0) {
        onClose();
        return;
      }
    } else {
      payload.property = property;
      payload.name = name.trim();
      payload.start_date = startDate;
      payload.end_date = endDate;
      payload.post_notice = postNotice;
      if (canAdjust) {
        payload.adjust_in_bill = adjust;
        if (adjust) payload.rate_per_day = shownRate;
      }
    }

    setErrors({});
    setSubmitting(true);
    try {
      const saved = initial ? await updateFoodHoliday(initial.id, payload) : await createFoodHoliday(payload);
      await afterFoodHolidayChange();
      onSaved?.(saved);
      onClose();
    } catch (err) {
      if (err instanceof ApiError) {
        const fields: Record<string, string> = {};
        for (const field of FIELDS) {
          const message = err.fieldError(field);
          if (message) fields[field] = message;
        }
        setErrors(Object.keys(fields).length > 0 ? fields : { form: err.message });
        // Locked (or otherwise changed) by someone else since this page loaded: show what is true now.
        if (err.status === 409) await afterFoodHolidayChange();
      } else {
        setErrors({ form: t("errSaveFailed") });
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Sheet open onClose={onClose} title={creating ? t("addTitle") : t("editTitle")}>
      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        {creating ? (
          <div className="space-y-1.5">
            <label htmlFor="holiday-property" className={LABEL}>
              {t("property")}
            </label>
            <select
              id="holiday-property"
              value={property}
              onChange={(event) => setProperty(event.target.value)}
              className={INPUT}
            >
              <option value="">—</option>
              {properties.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            {errors.property && <p className="text-xs text-status-critical">{errors.property}</p>}
          </div>
        ) : (
          <p className="text-sm text-ink-muted">{initial?.property_name}</p>
        )}

        <div className="space-y-1.5">
          <label htmlFor="holiday-name" className={LABEL}>
            {t("name")}
          </label>
          <input
            id="holiday-name"
            type="text"
            value={name}
            maxLength={100}
            placeholder={t("namePlaceholder")}
            onChange={(event) => setName(event.target.value)}
            className={INPUT}
          />
          {errors.name && <p className="text-xs text-status-critical">{errors.name}</p>}
        </div>

        {locked && (
          <p role="note" className="rounded-xl border border-status-warn/30 bg-status-warn-soft p-3 text-xs text-ink-muted">
            {t("lockedNote")}
          </p>
        )}

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <label htmlFor="holiday-start" className={LABEL}>
              {t("startDate")}
            </label>
            <input
              id="holiday-start"
              type="date"
              value={startDate}
              disabled={locked}
              onChange={(event) => setStartDate(event.target.value)}
              className={INPUT}
            />
            {errors.start_date && <p className="text-xs text-status-critical">{errors.start_date}</p>}
          </div>
          <div className="space-y-1.5">
            <label htmlFor="holiday-end" className={LABEL}>
              {t("endDate")}
            </label>
            <input
              id="holiday-end"
              type="date"
              value={endDate}
              min={startDate || undefined}
              disabled={locked}
              onChange={(event) => setEndDate(event.target.value)}
              className={INPUT}
            />
            {errors.end_date && <p className="text-xs text-status-critical">{errors.end_date}</p>}
          </div>
        </div>
        {days > 0 && <p className="text-xs text-ink-muted">{t("dayCount", { count: days })}</p>}

        {canAdjust && (
          <div className="space-y-3 rounded-xl border border-border p-3">
            <label htmlFor="holiday-adjust" className="flex items-start gap-3 cursor-pointer">
              <input
                id="holiday-adjust"
                type="checkbox"
                checked={adjust}
                disabled={locked}
                onChange={(event) => setAdjust(event.target.checked)}
                className="mt-0.5 size-4 accent-accent"
              />
              <span>
                <span className="block text-sm font-semibold text-ink">{t("adjust")}</span>
                <span className="block text-xs text-ink-muted">{t("adjustHint")}</span>
              </span>
            </label>
            {adjust && rateAvailable && (
              <div className="space-y-1.5">
                <label htmlFor="holiday-rate" className={LABEL}>
                  {t("rate")}
                </label>
                <input
                  id="holiday-rate"
                  type="text"
                  inputMode="decimal"
                  value={shownRate}
                  disabled={locked}
                  onChange={(event) => {
                    setRate(event.target.value);
                    setRateTouched(true);
                  }}
                  className={INPUT}
                />
                {errors.rate_per_day ? (
                  <p className="text-xs text-status-critical">{errors.rate_per_day}</p>
                ) : (
                  creating &&
                  settingsLoaded &&
                  !defaultRate && <p className="text-xs text-ink-faint">{t("rateNoDefault")}</p>
                )}
              </div>
            )}
          </div>
        )}

        {creating && (
          <label htmlFor="holiday-notice" className="flex items-start gap-3 cursor-pointer">
            <input
              id="holiday-notice"
              type="checkbox"
              checked={postNotice}
              onChange={(event) => setPostNotice(event.target.checked)}
              className="mt-0.5 size-4 accent-accent"
            />
            <span>
              <span className="block text-sm font-semibold text-ink">{t("postNotice")}</span>
              <span className="block text-xs text-ink-muted">{t("postNoticeHint")}</span>
            </span>
          </label>
        )}

        {errors.form && (
          <p role="alert" className="text-sm text-status-critical">
            {errors.form}
          </p>
        )}
        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded-xl bg-accent py-2.5 text-sm font-semibold text-ink-inverse transition-colors hover:bg-accent-hover disabled:opacity-60 cursor-pointer"
        >
          {submitting ? t("submitting") : creating ? t("submit") : t("save")}
        </button>
      </form>
    </Sheet>
  );
}
