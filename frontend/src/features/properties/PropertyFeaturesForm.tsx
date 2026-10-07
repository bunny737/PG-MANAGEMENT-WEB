"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { AlertTriangle, ArrowLeft, CheckCircle2, ChevronRight, LoaderCircle, Save } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  ApiError,
  FEATURE_DRAFT_PREFIX,
  createTenantFeature,
  getProperty,
  listBuildings,
  listFeatureCatalog,
  listPropertyFeatures,
  listTenantFeatures,
  replacePropertyFeatures,
  type Building,
  type FeatureCatalogItem,
  type Property,
  type PropertyFeaturesState,
  type TenantFeature,
} from "@/lib/api";
import { usePermissions } from "@/lib/permissions";
import { FeaturePicker, featureKey, keyToRef, toFeatureRefs, type FeatureSelection } from "./FeaturePicker";

/** Stable string for "has anything changed since the last load/save". */
function snapshot(selection: FeatureSelection, excluded: string[]) {
  return JSON.stringify([Object.entries(selection).sort(), [...excluded].sort()]);
}

function readDraft(propertyId: string): FeatureSelection | null {
  try {
    const raw = sessionStorage.getItem(FEATURE_DRAFT_PREFIX + propertyId);
    return raw ? (JSON.parse(raw) as FeatureSelection) : null;
  } catch {
    return null;
  }
}

export function PropertyFeaturesForm({ propertyId }: { propertyId: string }) {
  const t = useTranslations("properties.features");
  const tCommon = useTranslations("common");
  const { ready, can } = usePermissions();
  const canEdit = can("manage_property_features");

  const [property, setProperty] = useState<Property | null>(null);
  const [buildings, setBuildings] = useState<Building[]>([]);
  const [catalog, setCatalog] = useState<FeatureCatalogItem[]>([]);
  const [customFeatures, setCustomFeatures] = useState<TenantFeature[]>([]);
  const [scope, setScope] = useState<string | null>(null);
  const [state, setState] = useState<PropertyFeaturesState | null>(null);
  const [selection, setSelection] = useState<FeatureSelection>({});
  const [excluded, setExcluded] = useState<string[]>([]);
  const [saved, setSaved] = useState("");

  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState("");
  const [showSuccess, setShowSuccess] = useState(false);
  const [draftRestored, setDraftRestored] = useState(false);

  const isDirty = snapshot(selection, excluded) !== saved;

  const applyState = useCallback((next: PropertyFeaturesState) => {
    const ownSource = next.building ? "building" : "property";
    const own: FeatureSelection = {};
    for (const item of next.items) {
      if (item.source === ownSource) own[featureKey(item)] = item.is_paid;
    }
    const suppressed = next.building ? next.excluded.map(featureKey) : [];
    setState(next);
    setSelection(own);
    setExcluded(suppressed);
    setSaved(snapshot(own, suppressed));
    return own;
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      getProperty(propertyId),
      listBuildings(propertyId),
      listFeatureCatalog(),
      listTenantFeatures(),
      listPropertyFeatures(propertyId),
    ])
      .then(([propertyData, buildingData, catalogData, customData, featureData]) => {
        if (cancelled) return;
        setProperty(propertyData);
        setBuildings(buildingData.sort((a, b) => a.order - b.order));
        setCatalog(catalogData);
        setCustomFeatures(customData);
        const own = applyState(featureData);
        // A selection made while creating the PG that failed to save then.
        const draft = readDraft(propertyId);
        if (draft && Object.keys(own).length === 0) {
          setSelection(draft);
          setDraftRestored(true);
        }
        setIsLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError && err.status === 403 ? t("errPermission") : t("errLoadFailed"));
        setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [propertyId, t, applyState]);

  useEffect(() => {
    if (!isDirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [isDirty]);

  const confirmDiscard = () => !isDirty || window.confirm(t("unsavedChanges"));

  const handleScopeChange = async (next: string | null) => {
    if (next === scope || !confirmDiscard()) return;
    setError("");
    try {
      applyState(await listPropertyFeatures(propertyId, next));
      setScope(next);
      setDraftRestored(false);
    } catch {
      setError(t("errLoadFailed"));
    }
  };

  const handleSave = async () => {
    setError("");
    setIsSaving(true);
    try {
      const next = await replacePropertyFeatures(propertyId, {
        building: scope,
        items: toFeatureRefs(selection),
        ...(scope ? { excluded: excluded.map((key) => keyToRef(key)) } : {}),
      });
      applyState(next);
      sessionStorage.removeItem(FEATURE_DRAFT_PREFIX + propertyId);
      setDraftRestored(false);
      setShowSuccess(true);
      setTimeout(() => setShowSuccess(false), 4000);
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) setError(t("errPermission"));
      else if (err instanceof ApiError && err.status === 400) setError(err.message);
      else setError(t("errSaveFailed"));
    } finally {
      setIsSaving(false);
    }
  };

  const handleCreateCustom = async (label: string) => {
    const feature = await createTenantFeature(label);
    setCustomFeatures((prev) => (prev.some((f) => f.id === feature.id) ? prev : [...prev, feature]));
    return feature;
  };

  const { inherited, retired } = useMemo(() => {
    const items = state?.items ?? [];
    return {
      inherited: scope ? [...items.filter((item) => item.source === "property"), ...(state?.excluded ?? [])] : [],
      retired: items.filter(
        (item) => !item.is_active && item.source === (scope ? "building" : "property") && featureKey(item) in selection
      ),
    };
  }, [state, scope, selection]);

  if (isLoading || !ready) {
    return (
      <div className="flex items-center justify-center gap-2 py-16 text-sm text-ink-muted">
        <LoaderCircle className="size-4.5 animate-spin" />
        {t("loading")}
      </div>
    );
  }

  if (!property || !state) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-status-critical/30 bg-status-critical-soft px-4 py-3 text-sm text-status-critical">
        <AlertTriangle className="size-4 shrink-0" />
        {error || t("errLoadFailed")}
      </div>
    );
  }

  const backHref = `/properties/${property.id}/buildings`;
  const guardNavigation = (event: React.MouseEvent) => {
    if (!confirmDiscard()) event.preventDefault();
  };
  const { sharing_types: sharingTypes, room_categories: roomCategories } = state.derived;

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      {showSuccess && (
        <div className="fixed bottom-5 right-5 z-50 flex max-w-sm items-center gap-3 rounded-xl border border-emerald-100 bg-emerald-50 p-4 text-emerald-800 shadow-xl">
          <CheckCircle2 className="size-5 shrink-0 text-emerald-600" />
          <span className="text-sm font-semibold">{t("savedToast")}</span>
        </div>
      )}

      <div className="flex items-center gap-3">
        <Link
          href={backHref}
          onClick={guardNavigation}
          className="inline-flex items-center justify-center rounded-full border border-border p-2 transition-colors hover:bg-surface-page"
        >
          <ArrowLeft className="size-5 text-ink-muted" />
        </Link>
        <div>
          <nav aria-label="Breadcrumb" className="mb-1 flex items-center text-xs text-ink-muted">
            <ol className="inline-flex items-center space-x-1">
              <li>
                <Link href="/properties" onClick={guardNavigation} className="font-medium transition-colors hover:text-accent">
                  {tCommon("nav.properties")}
                </Link>
              </li>
              <li className="flex items-center">
                <ChevronRight className="mx-1 size-3 text-ink-faint" />
                <Link href={backHref} onClick={guardNavigation} className="font-medium transition-colors hover:text-accent">
                  {property.name}
                </Link>
              </li>
              <li className="flex items-center">
                <ChevronRight className="mx-1 size-3 text-ink-faint" />
                <span className="font-semibold text-ink">{t("title")}</span>
              </li>
            </ol>
          </nav>
          <h1 className="text-xl font-bold tracking-tight text-ink">{t("title")}</h1>
          <p className="text-xs text-ink-muted">{t("subtitle")}</p>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-status-critical/30 bg-status-critical-soft px-4 py-3 text-sm text-status-critical">
          <AlertTriangle className="size-4 shrink-0" />
          {error}
        </div>
      )}
      {draftRestored && (
        <div className="rounded-xl border border-accent/15 bg-accent-soft px-4 py-3 text-xs text-ink-muted">
          {t("draftRestored")}
        </div>
      )}

      {/* Most PGs are a single building, so the scope choice only appears when it means something. */}
      {buildings.length > 1 && (
        <div className="space-y-1.5">
          <label htmlFor="feature-scope" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
            {t("scopeLabel")}
          </label>
          <select
            id="feature-scope"
            value={scope ?? ""}
            onChange={(e) => void handleScopeChange(e.target.value || null)}
            className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2.5 text-sm text-ink outline-none transition-all focus:border-accent focus:ring-4 focus:ring-accent/15"
          >
            <option value="">{t("scopeWholePg")}</option>
            {buildings.map((building) => (
              <option key={building.id} value={building.id}>
                {t("scopeBuilding", { name: building.name })}
              </option>
            ))}
          </select>
          <p className="text-[11px] text-ink-faint">{scope ? t("scopeBuildingHint") : t("scopeHint")}</p>
        </div>
      )}

      {(sharingTypes.length > 0 || roomCategories.length > 0) && (
        <div className="space-y-2 rounded-2xl border border-border bg-surface-page p-4">
          <p className="text-xs font-bold uppercase tracking-wider text-ink-faint">{t("derivedTitle")}</p>
          <div className="flex flex-wrap gap-2">
            {sharingTypes.map((count) => (
              <span key={count} className="rounded-full border border-border bg-surface-card px-3 py-1 text-xs text-ink-muted">
                {t("derivedSharing", { count })}
              </span>
            ))}
            {roomCategories.map((category) => (
              <span key={category} className="rounded-full border border-border bg-surface-card px-3 py-1 text-xs text-ink-muted">
                {category === "ac" ? t("derivedAc") : t("derivedNonAc")}
              </span>
            ))}
          </div>
          <p className="text-[11px] text-ink-faint">
            {t("derivedHint")}{" "}
            <Link href={backHref} onClick={guardNavigation} className="font-semibold text-accent hover:underline">
              {t("derivedLink")}
            </Link>
          </p>
        </div>
      )}

      <div className="rounded-2xl border border-border bg-surface-card p-5 shadow-sm">
        <FeaturePicker
          catalog={catalog}
          customFeatures={customFeatures}
          value={selection}
          onChange={setSelection}
          onCreateCustom={handleCreateCustom}
          retired={retired}
          inherited={inherited}
          excluded={excluded}
          onExcludedChange={setExcluded}
          disabled={!canEdit || isSaving}
        />
      </div>

      {canEdit && (
        <div className="flex justify-end gap-3 pt-2">
          <Link
            href={backHref}
            onClick={guardNavigation}
            className="rounded-xl border border-border bg-surface-page px-5 py-2.5 text-xs font-bold text-ink-muted transition-colors hover:bg-surface-card hover:text-ink"
          >
            {tCommon("actions.cancel")}
          </Link>
          <button
            type="button"
            onClick={() => void handleSave()}
            disabled={isSaving || !isDirty}
            className="inline-flex cursor-pointer items-center justify-center gap-1.5 rounded-xl bg-accent px-5 py-2.5 text-xs font-bold text-ink-inverse transition-all hover:bg-accent-hover active:scale-[0.98] disabled:cursor-default disabled:opacity-50"
          >
            <Save className="size-4" />
            {isSaving ? t("saving") : t("save")}
          </button>
        </div>
      )}
    </div>
  );
}
