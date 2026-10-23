"use client";

import React, { useMemo, useState } from "react";
import { Ban, LoaderCircle, Plus, RotateCcw, Search, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { ApiError, type FeatureCatalogItem, type FeatureRef, type PropertyFeature, type TenantFeature } from "@/lib/api";
import { normaliseFeatureText } from "@/lib/featureText";

/** Selected features keyed by `featureKey`; the value is `is_paid`. */
export type FeatureSelection = Record<string, boolean>;

/** One key space for platform and custom features — mirrors the backend's `identity()`. */
export function featureKey(feature: { code?: string | null; tenant_feature?: string | null }): string {
  return feature.code ? `catalog:${feature.code}` : `custom:${feature.tenant_feature}`;
}

export function toFeatureRefs(selection: FeatureSelection): FeatureRef[] {
  return Object.entries(selection).map(([key, isPaid]) => keyToRef(key, isPaid));
}

export function keyToRef(key: string, isPaid = false): FeatureRef {
  const [type, id] = [key.slice(0, key.indexOf(":")), key.slice(key.indexOf(":") + 1)];
  return type === "catalog" ? { code: id, is_paid: isPaid } : { tenant_feature: id, is_paid: isPaid };
}

const MAX_LABEL_LENGTH = 60;
// Rules, not amenities: "Included / Extra cost" makes no sense for them.
const NO_PRICE_CATEGORY = "policies";
const POPULAR_ID_PREFIX = "popular";

interface PickerOption {
  key: string;
  label: string;
  category: string;
  categoryLabel: string;
  isPopular: boolean;
}

interface FeaturePickerProps {
  catalog: FeatureCatalogItem[];
  customFeatures: TenantFeature[];
  value: FeatureSelection;
  onChange: (next: FeatureSelection) => void;
  /** Creates a tenant feature; resolves to it. A catalogue duplicate rejects with an ApiError carrying `catalog_code`. */
  onCreateCustom: (label: string) => Promise<TenantFeature>;
  /** Selected features that were retired after being assigned — shown read-only until removed. */
  retired?: PropertyFeature[];
  /** Building scope: features inherited from the whole PG. */
  inherited?: PropertyFeature[];
  /** Building scope: keys of inherited features this building does not offer. */
  excluded?: string[];
  onExcludedChange?: (next: string[]) => void;
  disabled?: boolean;
  /** "compact" leads with the popular shortlist and keeps the rest collapsed. */
  variant?: "compact" | "full";
}

export function FeaturePicker({
  catalog,
  customFeatures,
  value,
  onChange,
  onCreateCustom,
  retired = [],
  inherited = [],
  excluded = [],
  onExcludedChange,
  disabled = false,
  variant = "full",
}: FeaturePickerProps) {
  const t = useTranslations("properties.features");
  const [query, setQuery] = useState("");
  const [newLabel, setNewLabel] = useState("");
  const [addError, setAddError] = useState("");
  const [addNotice, setAddNotice] = useState("");
  const [isAdding, setIsAdding] = useState(false);

  const customGroupLabel = t("yourFeaturesGroup");
  const options = useMemo<PickerOption[]>(
    () => [
      ...catalog.map((item) => ({
        key: featureKey({ code: item.code }),
        label: item.label,
        category: item.category,
        categoryLabel: item.category_label,
        isPopular: item.is_popular,
      })),
      ...customFeatures
        .filter((feature) => feature.is_active)
        .map((feature) => ({
          key: featureKey({ tenant_feature: feature.id }),
          label: feature.label,
          category: "custom",
          categoryLabel: customGroupLabel,
          isPopular: false,
        })),
    ],
    [catalog, customFeatures, customGroupLabel]
  );

  const needle = normaliseFeatureText(query);
  const visible = needle ? options.filter((option) => normaliseFeatureText(option.label).includes(needle)) : options;
  const groups = useMemo(() => {
    const byCategory = new Map<string, { label: string; options: PickerOption[] }>();
    for (const option of visible) {
      const group = byCategory.get(option.category) ?? { label: option.categoryLabel, options: [] };
      group.options.push(option);
      byCategory.set(option.category, group);
    }
    return Array.from(byCategory.entries());
  }, [visible]);
  const popular = variant === "compact" && !needle ? options.filter((option) => option.isPopular) : [];

  const select = (key: string) => {
    if (!(key in value)) onChange({ ...value, [key]: false });
    if (excluded.includes(key)) onExcludedChange?.(excluded.filter((k) => k !== key));
  };

  const toggle = (key: string) => {
    if (key in value) {
      const next = { ...value };
      delete next[key];
      onChange(next);
    } else {
      select(key);
    }
  };

  const toggleExcluded = (key: string) => {
    if (excluded.includes(key)) {
      onExcludedChange?.(excluded.filter((k) => k !== key));
      return;
    }
    onExcludedChange?.([...excluded, key]);
    if (key in value) {
      const next = { ...value };
      delete next[key];
      onChange(next);
    }
  };

  const handleAdd = async () => {
    const label = newLabel.trim().replace(/\s+/g, " ");
    const wanted = normaliseFeatureText(label);
    setAddError("");
    setAddNotice("");
    if (!wanted) return setAddError(t("errLabelRequired"));
    if (label.length > MAX_LABEL_LENGTH) return setAddError(t("errLabelTooLong", { max: MAX_LABEL_LENGTH }));

    const existing = options.find((option) => normaliseFeatureText(option.label) === wanted);
    if (existing) {
      select(existing.key);
      setAddNotice(t("alreadyInCatalog", { label: existing.label }));
      setNewLabel("");
      return;
    }

    setIsAdding(true);
    try {
      const feature = await onCreateCustom(label);
      select(featureKey({ tenant_feature: feature.id }));
      setNewLabel("");
    } catch (err) {
      // The server knows aliases the client doesn't ("generator" = power backup).
      const code = err instanceof ApiError ? err.body.catalog_code : undefined;
      const match = typeof code === "string" && options.find((option) => option.key === featureKey({ code }));
      if (match) {
        select(match.key);
        setAddNotice(t("alreadyInCatalog", { label: match.label }));
        setNewLabel("");
      } else {
        setAddError(err instanceof ApiError && err.status === 400 ? err.message : t("errAddFailed"));
      }
    } finally {
      setIsAdding(false);
    }
  };

  const renderOption = (option: PickerOption, idPrefix = "feature") => {
    const checked = option.key in value;
    const id = `${idPrefix}-${option.key}`;
    return (
      <div key={option.key} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
        <label htmlFor={id} className="flex items-center gap-2.5 text-sm text-ink cursor-pointer">
          <input
            id={id}
            type="checkbox"
            checked={checked}
            onChange={() => toggle(option.key)}
            disabled={disabled}
            className="size-4 accent-accent"
          />
          {option.label}
        </label>
        {checked && option.category !== NO_PRICE_CATEGORY && (
          <div className="inline-flex overflow-hidden rounded-lg border border-border text-[11px] font-semibold">
            {[false, true].map((isPaid) => (
              <button
                key={String(isPaid)}
                type="button"
                disabled={disabled}
                onClick={() => onChange({ ...value, [option.key]: isPaid })}
                className={`px-2.5 py-1 transition-colors cursor-pointer ${
                  value[option.key] === isPaid ? "bg-accent text-ink-inverse" : "bg-surface-card text-ink-muted hover:bg-surface-page"
                }`}
              >
                {isPaid ? t("paidLabel") : t("includedLabel")}
              </button>
            ))}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="relative min-w-52 flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-ink-faint" />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("searchPlaceholder")}
            aria-label={t("searchPlaceholder")}
            className="w-full rounded-xl border border-border bg-surface-card py-2 pl-9 pr-3 text-sm text-ink outline-none transition-all focus:border-accent focus:ring-4 focus:ring-accent/15"
          />
        </div>
        <span className="text-xs font-semibold text-ink-muted">
          {t("selectedCount", { count: Object.keys(value).length })}
        </span>
      </div>

      {retired.length > 0 && (
        <div className="rounded-xl border border-status-critical/30 bg-status-critical-soft p-3 space-y-2">
          <p className="text-xs font-bold text-status-critical">{t("retiredTitle")}</p>
          <p className="text-[11px] text-ink-muted">{t("retiredHint")}</p>
          {retired.map((feature) => (
            <div key={feature.id} className="flex items-center justify-between gap-2 text-sm text-ink">
              <span>{feature.label}</span>
              <button
                type="button"
                disabled={disabled}
                onClick={() => toggle(featureKey(feature))}
                className="inline-flex items-center gap-1 text-xs font-semibold text-status-critical hover:underline cursor-pointer disabled:opacity-50"
              >
                <X className="size-3" />
                {t("removeRetired")}
              </button>
            </div>
          ))}
        </div>
      )}

      {inherited.length > 0 && (
        <div className="rounded-xl border border-border bg-surface-page p-3 space-y-2">
          <p className="text-xs font-bold text-ink">{t("inheritedTitle")}</p>
          <p className="text-[11px] text-ink-muted">{t("inheritedHint")}</p>
          <div className="flex flex-wrap gap-2">
            {inherited.map((feature) => {
              const key = featureKey(feature);
              const isExcluded = excluded.includes(key);
              return (
                <button
                  key={key}
                  type="button"
                  disabled={disabled}
                  onClick={() => toggleExcluded(key)}
                  title={isExcluded ? t("undoSuppress") : t("notInThisBuilding")}
                  className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors cursor-pointer disabled:cursor-default ${
                    isExcluded
                      ? "border-status-critical/40 bg-status-critical-soft text-status-critical line-through"
                      : "border-border bg-surface-card text-ink hover:border-status-critical/40"
                  }`}
                >
                  {feature.label}
                  {!disabled && (isExcluded ? <RotateCcw className="size-3" /> : <Ban className="size-3 text-ink-faint" />)}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {popular.length > 0 && (
        <fieldset className="rounded-xl border border-border p-3">
          <legend className="px-1.5 text-xs font-bold uppercase tracking-wider text-ink-faint">{t("popularTitle")}</legend>
          <div className="grid grid-cols-1 gap-x-6 sm:grid-cols-2">{popular.map((option) => renderOption(option, POPULAR_ID_PREFIX))}</div>
        </fieldset>
      )}

      {groups.length === 0 && <p className="py-2 text-sm text-ink-muted">{t("noMatches")}</p>}

      <div className={variant === "compact" ? "max-h-80 space-y-2 overflow-y-auto pr-1" : "space-y-2"}>
        {groups.map(([category, group]) => {
          const selectedInGroup = group.options.filter((option) => option.key in value).length;
          return (
            <details
              key={category}
              open={Boolean(needle) || variant === "full" || undefined}
              className="rounded-xl border border-border bg-surface-card px-3 py-2"
            >
              <summary className="flex cursor-pointer items-center justify-between text-sm font-semibold text-ink">
                {group.label}
                {selectedInGroup > 0 && (
                  <span className="rounded-full bg-accent-soft px-2 py-0.5 text-[10px] font-bold text-accent">
                    {selectedInGroup}
                  </span>
                )}
              </summary>
              {category === NO_PRICE_CATEGORY && (
                <p className="mt-2 text-[11px] text-ink-muted">{t("policyConfirmHint")}</p>
              )}
              <div className="mt-1 grid grid-cols-1 gap-x-6 sm:grid-cols-2">{group.options.map((option) => renderOption(option))}</div>
            </details>
          );
        })}
      </div>

      {!disabled && (
        // A div, not a <form>: this sits inside the property form, and nested forms are invalid.
        <div className="space-y-1.5 border-t border-border pt-4">
          <label htmlFor="feature-add-own" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
            {t("addOwnLabel")}
          </label>
          <div className="flex gap-2">
            <input
              id="feature-add-own"
              type="text"
              value={newLabel}
              maxLength={MAX_LABEL_LENGTH}
              onChange={(e) => setNewLabel(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  void handleAdd();
                }
              }}
              placeholder={t("addOwnPlaceholder")}
              className="w-full rounded-xl border border-border bg-surface-card px-4 py-2 text-sm text-ink outline-none transition-all focus:border-accent focus:ring-4 focus:ring-accent/15"
            />
            <button
              type="button"
              onClick={() => void handleAdd()}
              disabled={isAdding}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-xl border border-border bg-surface-card px-4 py-2 text-sm font-semibold text-ink hover:bg-surface-page cursor-pointer disabled:opacity-50"
            >
              {isAdding ? <LoaderCircle className="size-4 animate-spin" /> : <Plus className="size-4" />}
              {t("addOwnButton")}
            </button>
          </div>
          <p className="text-[11px] text-ink-faint">{t("addOwnHint")}</p>
          {addError && <p className="text-xs text-status-critical">{addError}</p>}
          {addNotice && <p className="text-xs text-accent">{addNotice}</p>}
        </div>
      )}
    </div>
  );
}
