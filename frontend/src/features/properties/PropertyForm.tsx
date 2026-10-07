"use client";

import React, { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, CloudUpload, X, Info, CheckCircle2, AlertTriangle, LoaderCircle } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import {
  ApiError,
  FEATURE_DRAFT_PREFIX,
  createProperty,
  createTenantFeature,
  deletePropertyImage,
  getProperty,
  listFeatureCatalog,
  listTenantFeatures,
  replacePropertyFeatures,
  updateProperty,
  uploadPropertyImage,
  type FeatureCatalogItem,
  type PropertyImage,
  type TenantFeature,
} from "@/lib/api";
import { FeaturePicker, toFeatureRefs, type FeatureSelection } from "./FeaturePicker";

const PROPERTY_TYPES = [
  { value: "pg", key: "pg" },
  { value: "boys_hostel", key: "boys_hostel" },
  { value: "girls_hostel", key: "girls_hostel" },
  { value: "co_living", key: "co_living" },
];

interface PendingImage {
  file: File;
  previewUrl: string;
}

interface PropertyFormProps {
  /** When provided, the form loads and edits this property instead of creating a new one. */
  propertyId?: string;
}

export function PropertyForm({ propertyId }: PropertyFormProps) {
  const isEditMode = Boolean(propertyId);
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const t = useTranslations("properties");

  const [name, setName] = useState("");
  const [propertyType, setPropertyType] = useState(PROPERTY_TYPES[0].value);
  const [addressLine, setAddressLine] = useState("");
  const [city, setCity] = useState("");
  const [state, setState] = useState("");
  const [contactNumber, setContactNumber] = useState("");
  const [contactEmail, setContactEmail] = useState("");
  const [images, setImages] = useState<PendingImage[]>([]);
  const [existingImages, setExistingImages] = useState<PropertyImage[]>([]);
  const [removingImageId, setRemovingImageId] = useState<string | null>(null);

  const [isLoadingProperty, setIsLoadingProperty] = useState(isEditMode);
  const [loadError, setLoadError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [showSuccess, setShowSuccess] = useState(false);
  const [imageWarning, setImageWarning] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});

  // Features offered (create mode only — editing happens on the Features page).
  const [catalog, setCatalog] = useState<FeatureCatalogItem[]>([]);
  const [customFeatures, setCustomFeatures] = useState<TenantFeature[]>([]);
  const [features, setFeatures] = useState<FeatureSelection>({});
  const [featuresWarning, setFeaturesWarning] = useState("");
  const [savedPropertyId, setSavedPropertyId] = useState(propertyId ?? "");

  useEffect(() => {
    if (isEditMode) return;
    let cancelled = false;
    // Optional section: if the lists can't load, the form simply goes without it.
    Promise.all([listFeatureCatalog(), listTenantFeatures()])
      .then(([catalogData, customData]) => {
        if (cancelled) return;
        setCatalog(catalogData);
        setCustomFeatures(customData);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [isEditMode]);

  const handleCreateCustomFeature = async (label: string) => {
    const feature = await createTenantFeature(label);
    setCustomFeatures((prev) => (prev.some((f) => f.id === feature.id) ? prev : [...prev, feature]));
    return feature;
  };

  useEffect(() => {
    if (!propertyId) return;
    let cancelled = false;
    getProperty(propertyId)
      .then((property) => {
        if (cancelled) return;
        setName(property.name);
        setPropertyType(property.property_type);
        setAddressLine(property.address_line);
        setCity(property.city);
        setState(property.state);
        setContactNumber(property.contact_number);
        setContactEmail(property.contact_email ?? "");
        setExistingImages(property.images);
        setIsLoadingProperty(false);
      })
      .catch(() => {
        if (cancelled) return;
        setLoadError(t("form.errLoadFailed"));
        setIsLoadingProperty(false);
      });
    return () => {
      cancelled = true;
    };
  }, [propertyId, t]);

  const handleFilesSelected = (fileList: FileList | null) => {
    if (!fileList) return;
    const next = Array.from(fileList).map((file) => ({ file, previewUrl: URL.createObjectURL(file) }));
    setImages((prev) => [...prev, ...next]);
  };

  const handleRemoveImage = (index: number) => {
    setImages((prev) => {
      URL.revokeObjectURL(prev[index].previewUrl);
      return prev.filter((_, i) => i !== index);
    });
  };

  const handleRemoveExistingImage = async (image: PropertyImage) => {
    if (!propertyId) return;
    setRemovingImageId(image.id);
    try {
      await deletePropertyImage(propertyId, image.id);
      setExistingImages((prev) => prev.filter((img) => img.id !== image.id));
    } catch {
      setImageWarning(t("form.errImageRemoveFailed"));
    } finally {
      setRemovingImageId(null);
    }
  };

  const handleFormSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const newErrors: Record<string, string> = {};

    if (!name) newErrors.name = t("form.errNameRequired");
    if (!addressLine) newErrors.address = t("form.errAddressRequired");
    if (!city) newErrors.city = t("form.errCityRequired");
    if (!state) newErrors.state = t("form.errStateRequired");
    if (!contactNumber) newErrors.contactNumber = t("form.errContactRequired");

    if (Object.keys(newErrors).length > 0) {
      setErrors(newErrors);
      return;
    }

    setErrors({});
    setImageWarning("");
    setFeaturesWarning("");
    setIsLoading(true);

    try {
      const payload = {
        name,
        property_type: propertyType,
        address_line: addressLine,
        city,
        state,
        contact_number: contactNumber,
        contact_email: contactEmail || undefined,
      };

      const property = isEditMode && propertyId
        ? await updateProperty(propertyId, payload)
        : await createProperty(payload);

      const uploadResults = await Promise.allSettled(
        images.map((img) => uploadPropertyImage(property.id, img.file))
      );
      const failedCount = uploadResults.filter((r) => r.status === "rejected").length;
      if (failedCount > 0) {
        setImageWarning(
          t("form.errPhotosPartial", { count: failedCount, total: images.length })
        );
      }

      setSavedPropertyId(property.id);
      if (!isEditMode && Object.keys(features).length > 0) {
        try {
          await replacePropertyFeatures(property.id, { building: null, items: toFeatureRefs(features) });
        } catch {
          // The PG exists; keep the selection so the Features page can pick it up.
          sessionStorage.setItem(FEATURE_DRAFT_PREFIX + property.id, JSON.stringify(features));
          setFeaturesWarning(t("features.createPartialWarning"));
        }
      }

      setIsLoading(false);
      setShowSuccess(true);
    } catch (err) {
      setIsLoading(false);
      if (err instanceof ApiError && err.status === 400) {
        setErrors({
          name: err.fieldError("name") ?? "",
          address: err.fieldError("address_line") ?? "",
          city: err.fieldError("city") ?? "",
          state: err.fieldError("state") ?? "",
          contactNumber: err.fieldError("contact_number") ?? "",
          contactEmail: err.fieldError("contact_email") ?? "",
          form: err.fieldError("detail") ?? "",
        });
      } else if (err instanceof ApiError && err.status === 403) {
        setErrors({ form: t("form.errPermission") });
      } else {
        setErrors({ form: t("form.errServerUnreachable") });
      }
    }
  };

  const handleCloseModal = () => {
    setShowSuccess(false);
    router.push("/properties");
  };

  if (isLoadingProperty) {
    return (
      <div className="flex items-center justify-center gap-2 py-16 text-sm text-ink-muted">
        <LoaderCircle className="size-4.5 animate-spin" />
        {t("form.loadingProperty")}
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-status-critical/30 bg-status-critical-soft px-4 py-3 text-sm text-status-critical">
        <AlertTriangle className="size-4 shrink-0" />
        {loadError}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Success Modal Backdrop */}
      {showSuccess && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-6 bg-on-surface/40 backdrop-blur-sm transition-opacity duration-300">
          <div className="bg-surface-container-lowest p-8 rounded-2xl max-w-sm w-full text-center shadow-2xl border border-border">
            <div className="size-20 bg-blue-50 text-accent border border-blue-100 rounded-full flex items-center justify-center mx-auto mb-6">
              <CheckCircle2 className="size-10" />
            </div>
            <h3 className="text-xl font-bold text-ink mb-2">
              {isEditMode ? t("form.modalUpdatedTitle") : t("form.modalRegisteredTitle")}
            </h3>
            <p className="text-xs text-ink-muted mb-2 leading-relaxed">
              {isEditMode
                ? t("form.modalUpdatedDesc")
                : t("form.modalRegisteredDesc")}
            </p>
            {imageWarning && (
              <p className="text-xs text-status-critical mb-6 leading-relaxed">{imageWarning}</p>
            )}
            {featuresWarning && (
              <p className="text-xs text-status-critical mb-2 leading-relaxed">
                {featuresWarning}{" "}
                <Link href={`/properties/${savedPropertyId}/features`} className="font-semibold underline">
                  {t("features.setUpNow")}
                </Link>
              </p>
            )}
            <button
              onClick={handleCloseModal}
              className="w-full py-3 bg-surface-inverse text-ink-inverse font-bold rounded-xl hover:opacity-90 transition-opacity cursor-pointer text-sm mt-4"
            >
              {t("form.backToProperties")}
            </button>
          </div>
        </div>
      )}

      {/* Header */}
      <div className="flex items-center gap-3">
        <Link
          href="/properties"
          className="hover:bg-surface-page p-2 rounded-full transition-colors inline-flex items-center justify-center border border-border"
        >
          <ArrowLeft className="size-5 text-ink-muted" />
        </Link>
        <div>
          <h1 className="text-xl font-bold tracking-tight text-ink">
            {isEditMode ? t("form.editTitle") : t("form.addTitle")}
          </h1>
          <p className="text-xs text-ink-muted">
            {isEditMode
              ? t("form.editSubtitle")
              : t("form.addSubtitle")}
          </p>
        </div>
      </div>

      {errors.form && (
        <div className="flex items-center gap-2 rounded-xl border border-status-critical/30 bg-status-critical-soft px-4 py-3 text-sm text-status-critical">
          <AlertTriangle className="size-4 shrink-0" />
          {errors.form}
        </div>
      )}

      {/* Form Content */}
      <form onSubmit={handleFormSubmit} className="grid grid-cols-1 gap-6 lg:grid-cols-12 items-start">
        {/* Left Column Fields */}
        <div className="lg:col-span-7 space-y-6">
          <div className="bg-surface-card border border-border rounded-2xl p-5 shadow-sm space-y-4">
            <h2 className="text-sm font-bold uppercase tracking-wider text-ink-faint border-b border-border pb-2.5">
              {t("form.infoHeading")}
            </h2>

            {/* Property Name */}
            <div className="space-y-1.5">
              <label htmlFor="name" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                {t("form.propertyNameLabel")}
              </label>
              <input
                id="name"
                type="text"
                placeholder={t("form.propertyNamePlaceholder")}
                value={name}
                onChange={(e) => setName(e.target.value)}
                className={`w-full rounded-xl border ${
                  errors.name ? "border-status-critical focus:ring-status-critical/10" : "border-border focus:ring-accent/15 focus:border-accent"
                } bg-surface-card px-4 py-2.5 text-sm text-ink outline-none transition-all focus:ring-4`}
                disabled={isLoading}
              />
              {errors.name && <p className="text-xs text-status-critical">{errors.name}</p>}
            </div>

            {/* Property Type */}
            <div className="space-y-1.5">
              <label htmlFor="type" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                {t("form.propertyTypeLabel")}
              </label>
              <select
                id="type"
                value={propertyType}
                onChange={(e) => setPropertyType(e.target.value)}
                className="w-full rounded-xl border border-border bg-surface-card px-3.5 py-2.5 text-sm text-ink-muted outline-none transition-all focus:ring-4 focus:ring-accent/15 focus:border-accent"
                disabled={isLoading}
              >
                {PROPERTY_TYPES.map((option) => (
                  <option key={option.value} value={option.value}>
                    {t(`types.${option.key as "pg" | "boys_hostel" | "girls_hostel" | "co_living"}`)}
                  </option>
                ))}
              </select>
            </div>

            {/* Address */}
            <div className="space-y-1.5">
              <label htmlFor="address" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                {t("form.addressLabel")}
              </label>
              <textarea
                id="address"
                placeholder={t("form.addressPlaceholder")}
                value={addressLine}
                onChange={(e) => setAddressLine(e.target.value)}
                rows={3}
                className={`w-full rounded-xl border ${
                  errors.address ? "border-status-critical focus:ring-status-critical/10" : "border-border focus:ring-accent/15 focus:border-accent"
                } bg-surface-card px-4 py-2.5 text-sm text-ink outline-none transition-all focus:ring-4`}
                disabled={isLoading}
              />
              {errors.address && <p className="text-xs text-status-critical">{errors.address}</p>}
            </div>

            {/* City / State grid */}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <label htmlFor="city" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                  {t("form.cityLabel")}
                </label>
                <input
                  id="city"
                  type="text"
                  placeholder={t("form.cityPlaceholder")}
                  value={city}
                  onChange={(e) => setCity(e.target.value)}
                  className={`w-full rounded-xl border ${
                    errors.city ? "border-status-critical focus:ring-status-critical/10" : "border-border focus:ring-accent/15 focus:border-accent"
                  } bg-surface-card px-4 py-2.5 text-sm text-ink outline-none transition-all focus:ring-4`}
                  disabled={isLoading}
                />
                {errors.city && <p className="text-xs text-status-critical">{errors.city}</p>}
              </div>

              <div className="space-y-1.5">
                <label htmlFor="state" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                  {t("form.stateLabel")}
                </label>
                <input
                  id="state"
                  type="text"
                  placeholder={t("form.statePlaceholder")}
                  value={state}
                  onChange={(e) => setState(e.target.value)}
                  className={`w-full rounded-xl border ${
                    errors.state ? "border-status-critical focus:ring-status-critical/10" : "border-border focus:ring-accent/15 focus:border-accent"
                  } bg-surface-card px-4 py-2.5 text-sm text-ink outline-none transition-all focus:ring-4`}
                  disabled={isLoading}
                />
                {errors.state && <p className="text-xs text-status-critical">{errors.state}</p>}
              </div>
            </div>

            {/* Contact Number / Email grid */}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <label htmlFor="contactNumber" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                  {t("form.contactNumberLabel")}
                </label>
                <input
                  id="contactNumber"
                  type="tel"
                  placeholder={t("form.contactNumberPlaceholder")}
                  value={contactNumber}
                  onChange={(e) => setContactNumber(e.target.value.replace(/\D/g, "").slice(0, 15))}
                  className={`w-full rounded-xl border ${
                    errors.contactNumber ? "border-status-critical focus:ring-status-critical/10" : "border-border focus:ring-accent/15 focus:border-accent"
                  } bg-surface-card px-4 py-2.5 text-sm text-ink outline-none transition-all focus:ring-4`}
                  disabled={isLoading}
                />
                {errors.contactNumber && <p className="text-xs text-status-critical">{errors.contactNumber}</p>}
              </div>

              <div className="space-y-1.5">
                <label htmlFor="contactEmail" className="text-xs font-semibold uppercase tracking-wider text-ink-muted">
                  {t("form.contactEmailLabel")} <span className="normal-case text-ink-faint">{t("form.optionalText")}</span>
                </label>
                <input
                  id="contactEmail"
                  type="email"
                  placeholder={t("form.emailPlaceholder")}
                  value={contactEmail}
                  onChange={(e) => setContactEmail(e.target.value)}
                  className={`w-full rounded-xl border ${
                    errors.contactEmail ? "border-status-critical focus:ring-status-critical/10" : "border-border focus:ring-accent/15 focus:border-accent"
                  } bg-surface-card px-4 py-2.5 text-sm text-ink outline-none transition-all focus:ring-4`}
                  disabled={isLoading}
                />
                {errors.contactEmail && <p className="text-xs text-status-critical">{errors.contactEmail}</p>}
              </div>
            </div>
          </div>

          {isEditMode && propertyId ? (
            <div className="bg-surface-card border border-border rounded-2xl p-5 shadow-sm flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-sm font-bold uppercase tracking-wider text-ink-faint">{t("features.createSectionTitle")}</h2>
                <p className="text-xs text-ink-muted mt-1">{t("features.manageFromPageHint")}</p>
              </div>
              <Link
                href={`/properties/${propertyId}/features`}
                className="rounded-xl border border-border bg-surface-page px-4 py-2 text-xs font-bold text-ink hover:bg-surface-card transition-colors"
              >
                {t("features.manageFromPage")}
              </Link>
            </div>
          ) : (
            catalog.length > 0 && (
              <div className="bg-surface-card border border-border rounded-2xl p-5 shadow-sm space-y-4">
                <div className="border-b border-border pb-2.5">
                  <h2 className="text-sm font-bold uppercase tracking-wider text-ink-faint">
                    {t("features.createSectionTitle")}{" "}
                    <span className="normal-case text-ink-faint font-normal">{t("form.optionalText")}</span>
                  </h2>
                  <p className="text-xs text-ink-muted mt-1">{t("features.createSectionHint")}</p>
                </div>
                <FeaturePicker
                  catalog={catalog}
                  customFeatures={customFeatures}
                  value={features}
                  onChange={setFeatures}
                  onCreateCustom={handleCreateCustomFeature}
                  disabled={isLoading}
                  variant="compact"
                />
              </div>
            )
          )}
        </div>

        {/* Right Column: Image uploads */}
        <div className="lg:col-span-5 space-y-6">
          <div className="rounded-2xl border border-border bg-surface-card p-5 shadow-sm space-y-4">
            <h2 className="text-sm font-bold uppercase tracking-wider text-ink">{t("form.imagesHeading")}</h2>

            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              multiple
              className="hidden"
              onChange={(e) => {
                handleFilesSelected(e.target.files);
                e.target.value = "";
              }}
              disabled={isLoading}
            />

            {/* Bento-style Image Grid */}
            <div className="grid grid-cols-2 gap-4">
              {/* Upload trigger */}
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={isLoading}
                className="col-span-2 aspect-video bg-surface-page border-2 border-dashed border-border rounded-xl flex flex-col items-center justify-center text-ink-muted hover:bg-surface-card hover:border-accent/40 transition-colors cursor-pointer group disabled:opacity-50"
              >
                <CloudUpload className="size-8 text-ink-faint mb-2 group-hover:scale-110 transition-transform" />
                <p className="text-xs font-semibold text-ink">{t("form.uploadPhotos")}</p>
                <p className="text-[10px] text-ink-faint mt-0.5">{t("form.uploadHint")}</p>
              </button>

              {/* Existing photos (edit mode) */}
              {existingImages.map((img) => (
                <div key={img.id} className="aspect-square bg-surface-page rounded-xl overflow-hidden border border-border relative group">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={img.image} alt="Property" className="size-full object-cover" />
                  <button
                    type="button"
                    onClick={() => handleRemoveExistingImage(img)}
                    disabled={isLoading || removingImageId === img.id}
                    className="absolute top-2 right-2 bg-status-critical/80 hover:bg-status-critical text-white p-1 rounded-full opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer disabled:opacity-50"
                  >
                    {removingImageId === img.id ? (
                      <LoaderCircle className="size-3 animate-spin" />
                    ) : (
                      <X className="size-3" />
                    )}
                  </button>
                </div>
              ))}

              {/* Selected photo previews */}
              {images.map((img, idx) => (
                <div key={img.previewUrl} className="aspect-square bg-surface-page rounded-xl overflow-hidden border border-border relative group">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={img.previewUrl} alt={`Preview ${idx + 1}`} className="size-full object-cover" />
                  <button
                    type="button"
                    onClick={() => handleRemoveImage(idx)}
                    disabled={isLoading}
                    className="absolute top-2 right-2 bg-status-critical/80 hover:bg-status-critical text-white p-1 rounded-full opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer"
                  >
                    <X className="size-3" />
                  </button>
                </div>
              ))}
            </div>

            {/* Operational tip card */}
            <div className="bg-accent-soft border border-accent/15 p-4 rounded-xl flex gap-3.5 mt-2">
              <Info className="size-5 text-accent shrink-0" />
              <div className="space-y-0.5 text-xs">
                <p className="font-bold text-accent">{t("form.proTipTitle")}</p>
                <p className="text-ink-muted leading-relaxed">
                  {t("form.proTipDesc")}
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Form Action Register Bar (sticky layout) */}
        <div className="lg:col-span-12 border-t border-border bg-surface-card -mx-4 px-4 py-4 md:-mx-8 md:px-8 mt-6 flex justify-end">
          <button
            type="submit"
            disabled={isLoading}
            className="w-full sm:max-w-xs bg-accent text-ink-inverse hover:bg-accent-hover font-semibold py-3 px-6 rounded-xl flex items-center justify-center gap-2 cursor-pointer transition-colors shadow-sm disabled:opacity-50"
          >
            {isLoading
              ? isEditMode
                ? t("form.savingChanges")
                : t("form.processingRegistration")
              : isEditMode
                ? t("form.saveChangesButton")
                : t("form.registerButton")}
          </button>
        </div>
      </form>
    </div>
  );
}
